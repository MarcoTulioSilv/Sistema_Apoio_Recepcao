"""Carga inicial (DDS §14): simulação e efetivação, executadas pelo TI no servidor (DD-65), com os pacientes
criados pelo contrato do MOD-02 (DD-67) e as fichas da P1 guardadas cifradas até o aceite (DD-69)."""

from __future__ import annotations

import json
import random
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

from sar.modulo_01_acesso.contrato import AuditService, PermissionGuard
from sar.modulo_02_cadastro.contrato import (
    CadastroDaCarga,
    DadosCobertura,
    DadosContato,
    DadosPaciente,
    DadosTelefone,
    Ficha,
    LeituraCadastro,
    PacienteService,
    TipoCobertura,
    TipoTelefone,
)
from sar.modulo_06_configuracao.contrato import Municipio, Referencias
from sar.modulo_08_dados.interfaces.carga import DadosLinha, DadosLote, RepositorioCarga
from sar.modulo_08_dados.relogio import FUSO_CLINICA
from sar.modulo_10_carga import extrator, regras
from sar.modulo_10_carga.contrato import (
    CAMPOS_CONFERIDOS,
    Amostra,
    CampoConferencia,
    Conferencia,
    LinhaRelatorio,
    Modo,
    Original,
    PacienteSorteado,
    Relatorio,
    ResultadoConferencia,
    ResumoCarga,
    Tratamento,
)
from sar.nucleo.contexto import Contexto
from sar.nucleo.erros import ConfirmacaoNecessaria, NaoEncontrado, RegraViolada
from sar.nucleo.portas import Cifra, Finalidade
from sar.nucleo.uow import ExecutorDeOperacao, UnidadeDeTrabalho

GUARDA = PermissionGuard()
AMOSTRA = 15  # P-29: cerca de 10% da base
MOTIVO_MINIMO = 5  # descarte sem motivo de verdade não serve à revisão
MOTIVO_MAXIMO = 300  # carga_linha.excecao_motivo
# §4.9: a revisão (tratar exceções, conferir a amostra, sortear mais) é da recepção e da administração, pela mesma
# operação; ver o relatório é outra, e aceitar é só da administração.
VER = "carga.excecoes.ver"
CONFERIR = "carga.conferencia.registrar"
ACEITAR = "carga.aceitar"
PLANILHA_BASE = "p1"
# O MOD-02 recusa o paciente inteiro só nestes casos; o resto vira aviso dentro dele (DD-22).
EXCECOES_DO_CADASTRO = frozenset({"P-03.minimo", "prontuario.repetido", "cpf.repetido", "cns.repetido"})

Sorteador = Callable[[Sequence[int], int], list[int]]
Leitor = Callable[[Path], extrator.Planilhas]


def sorteio(ids: Sequence[int], quantos: int) -> list[int]:
    """Sorteio da amostra (§14.3) com o gerador do sistema operacional: ninguém escolhe quem será conferido."""
    return random.SystemRandom().sample(list(ids), min(quantos, len(ids)))


def associado(lote_id: int, planilha: str, numero_linha: int) -> bytes:
    """Amarra o cifrado à linha dona (DDS §3.9): trocar o conteúdo de uma linha por outro falha na decifragem."""
    return f"carga_linha:{lote_id}:{planilha}:{numero_linha}".encode()


def _texto(valor: regras.Valor) -> str | None:
    return valor.strftime("%d/%m/%Y") if isinstance(valor, date) else valor


def conteudo_original(bloco: regras.BlocoP1, item: regras.Planejado) -> bytes:
    """A ficha como estava na P1, mais as linhas da P4 e da P3 que se ligaram a ela: o lado esquerdo da conferência
    (§14.3). Nunca o registro interpretado, que é o que se quer conferir."""
    return json.dumps(
        {
            "p1": [[c.rotulo, _texto(c.valor)] for c in bloco.celulas],
            "p4": [{k: _texto(v) for k, v in linha.valores.items()} for linha in item.p4],
            "p3": [{"aba": linha.aba, "ano": linha.ano, "valores": list(linha.valores)} for linha in item.p3],
        },
        ensure_ascii=False,
    ).encode()


@dataclass(frozen=True, slots=True)
class _Resultado:
    bloco: regras.BlocoP1
    item: regras.Planejado
    desfecho: regras.Desfecho
    paciente_id: int | None


class _Desfazer(Exception):  # controle de fluxo interno da simulação, não erro de domínio
    """Leva o resultado da simulação para fora da transação, que é desfeita (DD-66)."""

    def __init__(self, resultado: tuple[list[_Resultado], dict[str, Any]]) -> None:
        super().__init__()
        self.resultado = resultado


class ServicoCarga:
    def __init__(
        self,
        executar: ExecutorDeOperacao,
        auditoria: AuditService,
        cadastro: CadastroDaCarga,
        referencias: Referencias,
        cifra: Cifra,
        pacientes: PacienteService,
        leitura: LeituraCadastro,
        sorteador: Sorteador = sorteio,
        ler: Leitor = extrator.ler,
    ) -> None:
        """O cadastro e a leitura vêm do MOD-02: a criação na transação da carga (DD-67), a ficha da conferência e a
        identificação dos sorteados."""
        self._executar = executar
        self._auditoria = auditoria
        self._cadastro = cadastro
        self._referencias = referencias
        self._cifra = cifra
        self._pacientes = pacientes
        self._leitura = leitura
        self._sortear = sorteador
        self._ler = ler

    def simular(self, contexto: Contexto, pasta: Path) -> ResumoCarga:
        return self._rodar(contexto, pasta, Modo.SIMULACAO)

    def efetivar(self, contexto: Contexto, pasta: Path) -> ResumoCarga:
        return self._rodar(contexto, pasta, Modo.EFETIVACAO)

    # ---------------------------------------------------------------- simulação e efetivação
    def _rodar(self, contexto: Contexto, pasta: Path, modo: Modo) -> ResumoCarga:
        operacao = "carga.simular" if modo is Modo.SIMULACAO else "carga.efetivar"
        GUARDA.exigir(contexto, operacao)
        planilhas = self._ler(pasta)
        hoje = contexto.instante.astimezone(FUSO_CLINICA).date()
        plano = regras.planejar(planilhas.p1, planilhas.p4, planilhas.p3, hoje)

        def importar(uow: UnidadeDeTrabalho) -> tuple[list[_Resultado], dict[str, Any]]:
            if uow.repositorio(RepositorioCarga).efetivacao(travar=True) is not None:
                raise RegraViolada("carga.ja_efetivada")  # DD-66: não há segunda carga
            convenios: dict[str, int] = {}
            for convenio in self._referencias.convenios_ativos(uow):
                convenios[regras.norm_nome(convenio.nome)] = convenio.id
            resultados = [
                self._importar(uow, contexto, operacao, bloco, item, convenios)
                for bloco, item in zip(planilhas.p1, plano.itens, strict=True)
            ]
            conta = regras.contagens(len(planilhas.p1), [r.desfecho for r in resultados], plano)
            if not conta["fecha"]:
                raise RegraViolada("carga.contagem_nao_fecha")  # RNF-103: nenhuma linha some em silêncio
            return resultados, conta

        if modo is Modo.SIMULACAO:

            def simular(uow: UnidadeDeTrabalho) -> None:
                raise _Desfazer(importar(uow))

            try:
                self._executar(simular)
                raise RuntimeError("inalcançável: a simulação sempre desfaz")
            except _Desfazer as desfeita:
                resultados, conta = desfeita.resultado
            lote_id = self._executar(lambda uow: self._gravar(uow, contexto, operacao, modo, resultados, conta))
        else:

            def efetivar(uow: UnidadeDeTrabalho) -> tuple[int, dict[str, Any]]:
                resultados, conta = importar(uow)
                return self._gravar(uow, contexto, operacao, modo, resultados, conta), conta

            lote_id, conta = self._executar(efetivar)
        return ResumoCarga(lote_id, modo, conta)

    def _importar(
        self,
        uow: UnidadeDeTrabalho,
        contexto: Contexto,
        operacao: str,
        bloco: regras.BlocoP1,
        item: regras.Planejado,
        convenios: dict[str, int],
    ) -> _Resultado:
        registro = item.registro
        if registro.excecao is not None:
            desfecho = regras.Desfecho(registro.numero_linha, False, registro.excecao, registro.avisos)
            return _Resultado(bloco, item, desfecho, None)
        avisos = list(registro.avisos)
        municipio = self._municipio(uow, registro, avisos)
        dados = DadosPaciente(
            prontuario=registro.prontuario, nome=registro.nome, data_nascimento=registro.nascimento,
            nome_mae=registro.nome_mae, cpf=registro.cpf, cns=registro.cns, rg=registro.rg,
            rg_orgao=registro.rg_orgao, logradouro=registro.logradouro, numero=registro.numero,
            complemento=registro.complemento, bairro=registro.bairro,
            municipio=municipio.codigo if municipio else None, cep=registro.cep,
        )  # fmt: skip
        telefones, contatos = _telefones_e_contatos(registro.telefones)
        try:
            criado = self._cadastro.criar_na_carga(
                uow, contexto, operacao, dados, registro.inicio, _cobertura(registro, convenios, avisos),
                telefones, contatos,
            )  # fmt: skip
        except RegraViolada as erro:
            if erro.codigo not in EXCECOES_DO_CADASTRO:
                raise
            desfecho = regras.Desfecho(registro.numero_linha, False, erro.codigo, tuple(avisos))
            return _Resultado(bloco, item, desfecho, None)
        desfecho = regras.Desfecho(registro.numero_linha, True, None, (*avisos, *criado.avisos))
        return _Resultado(bloco, item, desfecho, criado.paciente_id)

    def _municipio(self, uow: UnidadeDeTrabalho, registro: regras.RegistroP1, avisos: list[str]) -> Municipio | None:
        """RF-1104 e DD-53: 6 dígitos pela tabela, nunca pelo cálculo do dígito; 7 dígitos conferidos na tabela."""
        if registro.ibge is None:
            return None
        if len(registro.ibge) == 6:
            municipio = self._referencias.codigo_7_digitos(uow, registro.ibge)
        else:
            municipio = self._referencias.municipio(uow, registro.ibge)
        if municipio is None:
            avisos.append("ibge.sem_correspondencia")
        elif registro.municipio_nome and regras.norm_nome(municipio.nome) != regras.norm_nome(registro.municipio_nome):
            avisos.append("municipio.nome_divergente")  # o código prevalece; a conferência decide
        return municipio

    def _gravar(
        self,
        uow: UnidadeDeTrabalho,
        contexto: Contexto,
        operacao: str,
        modo: Modo,
        resultados: list[_Resultado],
        conta: dict[str, Any],
    ) -> int:
        """Na simulação, só as fichas com exceção ou aviso (o relatório); na efetivação, todas, para a conferência."""
        repositorio = uow.repositorio(RepositorioCarga)
        repositorio.apagar_linhas_de_simulacao()
        lote_id = repositorio.criar_lote(modo.value, contexto.instante)
        importadas: list[int] = []
        for resultado in resultados:
            desfecho = resultado.desfecho
            if modo is Modo.SIMULACAO and desfecho.importado and not desfecho.avisos:
                continue
            numero = resultado.bloco.numero_linha
            # Na simulação, o paciente foi desfeito junto com a transação: o id não existe mais.
            paciente_id = resultado.paciente_id if modo is Modo.EFETIVACAO else None
            nonce, cifrado = self._cifra.cifrar(
                Finalidade.CARGA, conteudo_original(resultado.bloco, resultado.item),
                associado(lote_id, PLANILHA_BASE, numero),
            )  # fmt: skip
            linha_id = repositorio.criar_linha(
                lote_id, PLANILHA_BASE, numero, cifrado, nonce, paciente_id, desfecho.excecao,
                _avisos_unicos(desfecho.avisos),
            )  # fmt: skip
            if paciente_id is not None:
                importadas.append(linha_id)
        if modo is Modo.EFETIVACAO:
            repositorio.marcar_amostra(self._sortear(importadas, AMOSTRA), 1)
        repositorio.concluir_lote(lote_id, "concluida", conta, contexto.instante)
        p1 = conta["p1"]
        self._auditoria.registrar(
            uow, contexto, operacao, "carga_lote", str(lote_id),
            {"linhas_p1": (None, p1["linhas"]), "importados": (None, p1["importados"]),
             "excecoes": (None, p1["excecoes"])},
        )  # fmt: skip
        return lote_id

    # ---------------------------------------------------------------- revisão (§14.3), pela recepção e administração
    def _original(self, lote_id: int, linha: DadosLinha) -> Original:
        claro = self._cifra.decifrar(
            Finalidade.CARGA,
            linha.nonce,
            linha.conteudo_cifrado,
            associado(lote_id, linha.planilha, linha.numero_linha),
        )
        dados = json.loads(claro)
        return Original(tuple((r, v) for r, v in dados["p1"]), tuple(dados["p4"]), tuple(dados["p3"]))

    def em_revisao(self, contexto: Contexto) -> bool:
        if not GUARDA.pode(contexto, VER):
            return False
        lote = self._executar(lambda uow: uow.repositorio(RepositorioCarga).ultimo_lote())
        return lote is not None and lote.situacao != "aceita"

    def relatorio(self, contexto: Contexto) -> Relatorio | None:
        GUARDA.exigir(contexto, VER)  # RF-1004: o TI não passa daqui

        def operacao(uow: UnidadeDeTrabalho) -> Relatorio | None:
            repositorio = uow.repositorio(RepositorioCarga)
            lote = repositorio.ultimo_lote()
            if lote is None:
                return None
            linhas = tuple(
                LinhaRelatorio(
                    linha.id,
                    linha.numero_linha,
                    linha.excecao_codigo,
                    linha.avisos,
                    Tratamento(linha.excecao_tratada) if linha.excecao_tratada else None,
                    linha.excecao_motivo,
                    linha.paciente_id,
                    self._original(lote.id, linha),
                )
                for linha in repositorio.linhas(lote.id)
                if linha.excecao_codigo or linha.avisos
            )
            self._auditoria.registrar(uow, contexto, VER, "carga_lote", str(lote.id), {"linhas": (None, len(linhas))})
            return Relatorio(lote.id, Modo(lote.modo), lote.concluido_em, lote.aceito_em, lote.contagens or {}, linhas)

        return self._executar(operacao)

    def tratar_excecao(
        self, contexto: Contexto, linha_id: int, tratamento: Tratamento, motivo: str | None, prontuario: str | None
    ) -> None:
        GUARDA.exigir(contexto, CONFERIR)
        motivo = " ".join((motivo or "").split()) or None
        if motivo is not None and len(motivo) > MOTIVO_MAXIMO:
            raise RegraViolada("carga.motivo", {"maximo": MOTIVO_MAXIMO})
        paciente_id: int | None = None
        if tratamento is Tratamento.DESCARTADA:
            if motivo is None or len(motivo) < MOTIVO_MINIMO:
                raise RegraViolada("carga.motivo", {"minimo": MOTIVO_MINIMO})
        else:
            numero = " ".join((prontuario or "").split())
            achados = [p for p in self._pacientes.buscar(contexto, numero) if p.prontuario == numero] if numero else []
            if not achados:
                raise RegraViolada("carga.paciente_nao_encontrado")
            paciente_id = achados[0].paciente_id

        def operacao(uow: UnidadeDeTrabalho) -> None:
            repositorio = uow.repositorio(RepositorioCarga)
            lote = _efetivacao_aberta(repositorio)
            linha = repositorio.linha(linha_id, travar=True)
            if linha is None or linha.lote_id != lote.id:
                raise NaoEncontrado()
            if linha.excecao_codigo is None:
                raise RegraViolada("carga.linha_sem_excecao")
            if paciente_id is not None:
                outra = repositorio.ligada_a(paciente_id)
                if outra is not None and outra.id != linha.id:
                    raise RegraViolada("carga.paciente_ja_ligado")
            repositorio.tratar(linha.id, tratamento.value, motivo or "", paciente_id)
            self._auditoria.registrar(
                uow, contexto, CONFERIR, "carga_linha", str(linha.id),
                {"excecao_tratada": (linha.excecao_tratada, tratamento.value),
                 "paciente_id": (linha.paciente_id, paciente_id)},
                motivo,
            )  # fmt: skip

        self._executar(operacao)

    def _amostra_em(self, uow: UnidadeDeTrabalho, lote: DadosLote) -> Amostra:
        repositorio = uow.repositorio(RepositorioCarga)
        sorteadas = [li for li in repositorio.linhas(lote.id) if li.amostra_rodada is not None and li.paciente_id]
        identificados = self._leitura.identificacoes(uow, [li.paciente_id or 0 for li in sorteadas])  # sem anulados
        conferencias = repositorio.conferencias()
        pacientes = []
        for linha in sorteadas:
            paciente_id = linha.paciente_id or 0
            dele = [c.resultado for c in conferencias if c.paciente_id == paciente_id]
            ident = identificados.get(paciente_id)
            pacientes.append(
                PacienteSorteado(
                    linha.id,
                    paciente_id,
                    linha.amostra_rodada or 1,
                    ident.nome if ident else None,
                    ident.prontuario if ident else None,
                    dele.count(ResultadoConferencia.CONFERIDO.value),
                    dele.count(ResultadoConferencia.DIVERGENTE.value),
                )
            )
        pacientes.sort(key=lambda p: (p.rodada, p.nome or "", p.linha_id))
        return Amostra(tuple(pacientes), max((p.rodada for p in pacientes), default=0))

    def amostra(self, contexto: Contexto) -> Amostra:
        GUARDA.exigir(contexto, CONFERIR)

        def operacao(uow: UnidadeDeTrabalho) -> Amostra:
            lote = uow.repositorio(RepositorioCarga).efetivacao()
            if lote is None or lote.situacao == "aceita":
                return Amostra((), 0)
            return self._amostra_em(uow, lote)

        return self._executar(operacao)

    @staticmethod
    def _sorteada(uow: UnidadeDeTrabalho, linha_id: int) -> tuple[DadosLote, DadosLinha, int]:
        repositorio = uow.repositorio(RepositorioCarga)
        lote = _efetivacao_aberta(repositorio)
        linha = repositorio.linha(linha_id)
        if linha is None or linha.lote_id != lote.id or linha.amostra_rodada is None or linha.paciente_id is None:
            raise NaoEncontrado()
        return lote, linha, linha.paciente_id

    def conferencia(self, contexto: Contexto, linha_id: int) -> Conferencia:
        GUARDA.exigir(contexto, CONFERIR)

        def operacao(uow: UnidadeDeTrabalho) -> tuple[Original, int, dict[str, str]]:
            lote, linha, paciente_id = self._sorteada(uow, linha_id)
            conferencias = uow.repositorio(RepositorioCarga).conferencias()
            feitos = {c.campo: c.resultado for c in conferencias if c.paciente_id == paciente_id}
            self._auditoria.registrar(uow, contexto, CONFERIR, "carga_linha", str(linha.id), motivo="consulta")
            return self._original(lote.id, linha), paciente_id, feitos

        original, paciente_id, feitos = self._executar(operacao)
        valores = valores_da_ficha(self._pacientes.ver_ficha(contexto, paciente_id))  # NaoEncontrado se anulado
        campos = tuple(
            CampoConferencia(
                campo, rotulo, valores.get(campo), ResultadoConferencia(feitos[campo]) if campo in feitos else None
            )
            for campo, rotulo in CAMPOS_CONFERIDOS
        )
        return Conferencia(linha_id, paciente_id, original, campos)

    def registrar_conferencia(
        self, contexto: Contexto, linha_id: int, campo: str, resultado: ResultadoConferencia
    ) -> None:
        GUARDA.exigir(contexto, CONFERIR)
        if campo not in dict(CAMPOS_CONFERIDOS):
            raise RegraViolada("carga.campo")
        usuario_id = contexto.usuario_id
        if usuario_id is None:
            raise RuntimeError("inalcançável: a conferência é de uma pessoa")

        def operacao(uow: UnidadeDeTrabalho) -> None:
            _, linha, paciente_id = self._sorteada(uow, linha_id)
            repositorio = uow.repositorio(RepositorioCarga)
            anteriores = [
                c.resultado for c in repositorio.conferencias() if (c.paciente_id, c.campo) == (paciente_id, campo)
            ]
            if repositorio.registrar_conferencia(paciente_id, campo, resultado.value, usuario_id, contexto.instante):
                anterior = anteriores[0] if anteriores else None
                self._auditoria.registrar(
                    uow, contexto, CONFERIR, "carga_linha", str(linha.id), {campo: (anterior, resultado.value)}
                )

        self._executar(operacao)

    def sortear_mais(self, contexto: Contexto) -> int:
        GUARDA.exigir(contexto, CONFERIR)

        def operacao(uow: UnidadeDeTrabalho) -> int:
            repositorio = uow.repositorio(RepositorioCarga)
            lote = _efetivacao_aberta(repositorio, travar=True)
            atual = self._amostra_em(uow, lote)
            if not atual.completa:
                raise RegraViolada("carga.amostra_incompleta")
            if not atual.divergencias:
                raise RegraViolada("carga.sem_divergencia")
            livres = [
                li.id
                for li in repositorio.linhas(lote.id)
                if li.paciente_id is not None and li.excecao_codigo is None and li.amostra_rodada is None
            ]
            sorteadas = self._sortear(livres, AMOSTRA)
            rodada = atual.rodadas + 1
            repositorio.marcar_amostra(sorteadas, rodada)
            self._auditoria.registrar(
                uow, contexto, CONFERIR, "carga_lote", str(lote.id),
                {"rodada": (atual.rodadas, rodada), "sorteados": (None, len(sorteadas))},
            )  # fmt: skip
            return len(sorteadas)

        return self._executar(operacao)

    def aceitar(self, contexto: Contexto, ativos_confirmados: int, confirmar_diferenca: bool = False) -> None:
        GUARDA.exigir(contexto, ACEITAR)
        if ativos_confirmados < 0:
            raise RegraViolada("carga.ativos_confirmados")
        usuario_id = contexto.usuario_id
        if usuario_id is None:
            raise RuntimeError("inalcançável: o aceite é de uma pessoa")

        def operacao(uow: UnidadeDeTrabalho) -> None:
            repositorio = uow.repositorio(RepositorioCarga)
            lote = _efetivacao_aberta(repositorio, travar=True)
            linhas = repositorio.linhas(lote.id)
            if any(li.excecao_codigo and not li.excecao_tratada for li in linhas):
                raise RegraViolada("carga.excecao_sem_tratamento")
            amostra = self._amostra_em(uow, lote)
            if not amostra.completa:
                raise RegraViolada("carga.amostra_incompleta")
            ligados = [li.paciente_id for li in linhas if li.paciente_id is not None]
            carregados = len(self._leitura.identificacoes(uow, ligados))  # sem os anulados depois da carga
            if carregados != ativos_confirmados and not confirmar_diferenca:
                raise ConfirmacaoNecessaria("ativos", {"carregados": carregados, "confirmados": ativos_confirmados})
            repositorio.aceitar(lote.id, contexto.instante, usuario_id, ativos_confirmados)
            linhas_apagadas, conferencias_apagadas = repositorio.apagar_area_de_trabalho()  # DD-69
            self._auditoria.registrar(
                uow, contexto, ACEITAR, "carga_lote", str(lote.id),
                {"ativos_confirmados": (None, ativos_confirmados), "carregados": (None, carregados),
                 "sorteados": (None, len(amostra.pacientes)), "divergencias": (None, amostra.divergencias),
                 "linhas_apagadas": (None, linhas_apagadas), "conferencias_apagadas": (None, conferencias_apagadas)},
            )  # fmt: skip

        self._executar(operacao)


def _efetivacao_aberta(repositorio: RepositorioCarga, travar: bool = False) -> DadosLote:
    lote = repositorio.efetivacao(travar=travar)
    if lote is None:
        raise RegraViolada("carga.sem_efetivacao")
    if lote.situacao == "aceita":
        raise RegraViolada("carga.aceita")
    return lote


def _data(valor: date | None) -> str | None:
    return valor.strftime("%d/%m/%Y") if valor else None


def _telefone(ddd: str, numero: str) -> str:
    return f"({ddd}) {numero[:-4]}-{numero[-4:]}"


def valores_da_ficha(ficha: Ficha) -> dict[str, str]:
    """O lado direito da conferência: cada campo do cadastro como texto, como a recepção lê a ficha."""
    d = ficha.dados
    partes = (d.logradouro, f"nº {d.numero}" if d.numero else None, d.complemento, d.bairro)
    telefones = [_telefone(t.ddd, t.numero) for t in ficha.telefones]
    for contato in ficha.contatos:
        grau = f" ({contato.parentesco})" if contato.parentesco else ""
        numeros = ", ".join(_telefone(t.ddd, t.numero) for t in contato.telefones)
        telefones.append(f"{contato.nome}{grau}: {numeros}" if numeros else f"{contato.nome}{grau}")
    primeiro = ficha.periodos[0] if ficha.periodos else None
    cobertura = primeiro.cobertura if primeiro else None
    convenio = None
    if cobertura is not None:
        convenio = "SUS" if cobertura.tipo is TipoCobertura.SUS else cobertura.convenio_nome
    valores = {
        "nome": d.nome,
        "prontuario": d.prontuario,
        "nome_mae": d.nome_mae,
        "data_nascimento": _data(d.data_nascimento),
        "cpf": f"{d.cpf[:3]}.{d.cpf[3:6]}.{d.cpf[6:9]}-{d.cpf[9:]}" if d.cpf else None,
        "rg": " ".join(v for v in (d.rg, d.rg_orgao) if v),
        "cns": d.cns,
        "endereco": ", ".join(v for v in partes if v),
        "municipio": f"{ficha.residencia.nome}-{ficha.residencia.uf}" if ficha.residencia else None,
        "cep": f"{d.cep[:5]}-{d.cep[5:]}" if d.cep else None,
        "telefones": "; ".join(telefones),
        "convenio": convenio,
        "inicio": _data(primeiro.inicio) if primeiro else None,
    }
    return {campo: valor for campo, valor in valores.items() if valor}


def _avisos_unicos(avisos: Sequence[str]) -> list[str]:
    return list(dict.fromkeys(avisos))


def _cobertura(registro: regras.RegistroP1, convenios: dict[str, int], avisos: list[str]) -> DadosCobertura | None:
    """'SUS' é o SUS; outro nome precisa estar cadastrado e ativo (RF-301). Sem convênio na ficha, sem cobertura."""
    if registro.convenio is None:
        return None
    nome = regras.norm_nome(registro.convenio)
    if nome in ("SUS", "SSUS"):
        return DadosCobertura(TipoCobertura.SUS)
    convenio_id = convenios.get(nome)
    if convenio_id is None:
        avisos.append("convenio.desconhecido")
        return None
    return DadosCobertura(TipoCobertura.CONVENIO, convenio_id)


def _telefones_e_contatos(
    lidos: Sequence[regras.TelefoneLido],
) -> tuple[list[DadosTelefone], list[DadosContato]]:
    """Os do paciente e os de cada contato, agrupados pelo nome (o mesmo contato pode ter dois números)."""
    do_paciente: list[DadosTelefone] = []
    contatos: dict[str, tuple[str, str | None, list[DadosTelefone]]] = {}
    for lido in lidos:
        telefone = DadosTelefone(lido.ddd, lido.numero, TipoTelefone(lido.tipo))
        if lido.contato is None:
            do_paciente.append(telefone)
            continue
        chave = regras.norm_nome(lido.contato)
        nome, grau, telefones = contatos.setdefault(chave, (lido.contato, lido.parentesco, []))
        telefones.append(telefone)
        if grau is None and lido.parentesco is not None:
            contatos[chave] = (nome, lido.parentesco, telefones)
    return do_paciente, [DadosContato(nome, grau, tuple(t)) for nome, grau, t in contatos.values()]
