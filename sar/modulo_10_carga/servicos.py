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
    TipoCobertura,
    TipoTelefone,
)
from sar.modulo_06_configuracao.contrato import Municipio, Referencias
from sar.modulo_08_dados.interfaces.carga import RepositorioCarga
from sar.modulo_08_dados.relogio import FUSO_CLINICA
from sar.modulo_10_carga import extrator, regras
from sar.modulo_10_carga.contrato import Modo, ResumoCarga
from sar.nucleo.contexto import Contexto
from sar.nucleo.erros import RegraViolada
from sar.nucleo.portas import Cifra, Finalidade
from sar.nucleo.uow import ExecutorDeOperacao, UnidadeDeTrabalho

GUARDA = PermissionGuard()
AMOSTRA = 15  # P-29: cerca de 10% da base
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
        sorteador: Sorteador = sorteio,
        ler: Leitor = extrator.ler,
    ) -> None:
        self._executar = executar
        self._auditoria = auditoria
        self._cadastro = cadastro
        self._referencias = referencias
        self._cifra = cifra
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
