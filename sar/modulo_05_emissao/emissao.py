"""Emissão de documentos (DDS §9.1, DD-42, DD-43, RNF-903): cada emissão lê o cadastro atual, preenche o modelo ativo
(ou monta o leiaute fixo do DOC-01, DD-106), converte em PDF e entrega em memória. Só fica registrado o modelo, a
versão, a referência, a competência, o instante e quem emitiu, com a auditoria na mesma transação.

Ordem: leitura (transação curta) → preenchimento e conversão (fora de transação, DD-59) → registro.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date

from sar.modulo_01_acesso.contrato import AuditService, PermissionGuard
from sar.modulo_02_cadastro.contrato import Identificacao, LeituraCadastro, PacienteService
from sar.modulo_03_operacao.contrato import LeituraOperacao
from sar.modulo_04_documentos.contrato import LeituraDocumentos
from sar.modulo_05_emissao import comum, ficha, pdf, regras
from sar.modulo_05_emissao.contrato import Documento, DocumentoEmitido, Modelo
from sar.modulo_05_emissao.conversor import ConversorDocumentos
from sar.modulo_05_emissao.modelos import arquivo_ativo
from sar.modulo_05_emissao.preenchimento import preencher
from sar.modulo_05_emissao.variaveis import nomes
from sar.modulo_06_configuracao.contrato import Referencias
from sar.modulo_08_dados.interfaces.emissao import DadosEmissao, RepositorioEmissao
from sar.nucleo.contexto import Contexto
from sar.nucleo.erros import AcessoNegado, ConfirmacaoNecessaria, NaoEncontrado, RegraViolada
from sar.nucleo.uow import ExecutorDeOperacao, UnidadeDeTrabalho

GUARDA = PermissionGuard()
TITULO_FICHA = "Ficha de cadastro do paciente"
TITULO_DECLARACAO = "Declaração de atendimento ao titular dos dados"
MODELO_DECLARACAO = "TITULAR"  # DD-105: leiaute fixo, sem modelo .docx


@dataclass(frozen=True, slots=True)
class _Preparo:
    """O que a leitura junta para o preenchimento."""

    versao: int
    arquivo: bytes
    valores: dict[str, str]
    logotipo: bytes | None
    referencia: str | None


class ServicoEmissao:
    def __init__(
        self,
        executar: ExecutorDeOperacao,
        auditoria: AuditService,
        referencias: Referencias,
        leitura_cadastro: LeituraCadastro,
        pacientes: PacienteService,
        leitura_operacao: LeituraOperacao,
        leitura_documentos: LeituraDocumentos,
        conversor: ConversorDocumentos,
    ) -> None:
        self._executar = executar
        self._auditoria = auditoria
        self._referencias = referencias
        self._cadastro = leitura_cadastro
        self._pacientes = pacientes
        self._operacao = leitura_operacao
        self._documentos = leitura_documentos
        self._conversor = conversor

    # ---------------------------------------------------------------- contrato
    def emitir(
        self,
        contexto: Contexto,
        documento: Documento,
        paciente_id: int,
        troca_id: int | None = None,
        confirmar_reemissao: bool = False,
    ) -> DocumentoEmitido:
        GUARDA.exigir(contexto, "emissao.documento.emitir")
        if documento is Documento.FICHA:
            return self._ficha(contexto, paciente_id)
        modelo = Modelo(documento.value)
        preparo = self._executar(
            lambda uow: self._preparar(uow, contexto, modelo, paciente_id, troca_id, confirmar_reemissao)
        )
        pdf_gerado = self._converter(modelo, preparo, {})
        self._registrar(contexto, documento.value, preparo.versao, paciente_id, preparo.referencia)
        return DocumentoEmitido(pdf_gerado, _nome_arquivo(documento.value, contexto))

    def emitir_cracha(self, contexto: Contexto, paciente_id: int) -> DocumentoEmitido:
        GUARDA.exigir(contexto, "emissao.cracha.emitir")
        preparo = self._executar(lambda uow: self._preparar(uow, contexto, Modelo.CRACHA, paciente_id, None, False))
        foto = self._documentos.foto(contexto, paciente_id)
        if foto is None:
            raise RegraViolada("cracha.sem_foto")
        pdf_gerado = self._converter(Modelo.CRACHA, preparo, {"foto": foto})
        self._registrar(contexto, Modelo.CRACHA.value, preparo.versao, paciente_id, None)
        return DocumentoEmitido(pdf_gerado, _nome_arquivo("cracha", contexto))

    def emitir_declaracao_titular(
        self, contexto: Contexto, paciente_id: int, recebida_em: date, paginas_documentos: int, referencia: str
    ) -> DocumentoEmitido:
        GUARDA.exigir(contexto, "titular.copia.gerar")

        def ler(uow: UnidadeDeTrabalho) -> tuple[comum.Comuns, Identificacao]:
            identificacao = self._cadastro.identificacao(uow, paciente_id)
            if identificacao is None:
                raise NaoEncontrado()
            return self._comuns(uow, contexto), identificacao

        comuns, identificacao = self._executar(ler)
        conteudo = pdf.html("declaracao_titular.html", {
            **comuns.valores, "titulo": TITULO_DECLARACAO, "logotipo": pdf.imagem_embutida(comuns.logotipo),
            "nome": identificacao.nome, "prontuario": identificacao.prontuario,
            "recebida_em": regras.data_curta(recebida_em), "paginas_documentos": paginas_documentos,
        })  # fmt: skip
        pdf_gerado = pdf.para_pdf(conteudo)
        self._registrar(contexto, MODELO_DECLARACAO, 0, paciente_id, referencia)
        return DocumentoEmitido(pdf_gerado, _nome_arquivo("declaracao-titular", contexto))

    # ---------------------------------------------------------------- etapas
    def _preparar(
        self,
        uow: UnidadeDeTrabalho,
        contexto: Contexto,
        modelo: Modelo,
        paciente_id: int,
        troca_id: int | None,
        confirmar_reemissao: bool,
    ) -> _Preparo:
        identificacao = self._cadastro.identificacao(uow, paciente_id)
        if identificacao is None:
            raise NaoEncontrado()
        comuns = self._comuns(uow, contexto)
        valores = {
            **comuns.valores,
            "nome": identificacao.nome,
            "data_nascimento": regras.data_curta(identificacao.data_nascimento),
            "nome_mae": identificacao.nome_mae or "",
        }
        referencia = None
        hoje = regras.hoje(contexto.instante)
        if modelo is Modelo.TROCA:
            troca = self._operacao.troca(uow, troca_id) if troca_id is not None else None
            if troca is None or troca.paciente_id != paciente_id:
                raise NaoEncontrado()  # só de troca registrada e não cancelada (§9.1)
            valores |= {
                "data_origem": regras.data_curta(troca.origem),
                "turno_origem": regras.turno(troca.turno_origem) if troca.turno_origem else "",
                "data_destino": regras.data_curta(troca.destino),
                "turno_destino": regras.turno(troca.turno_destino),
            }
            referencia = f"troca:{troca_id}"
        elif modelo is Modelo.EXTRA:
            turno = self._operacao.turno_em(uow, paciente_id, hoje)
            valores["turno"] = regras.turno(turno) if turno else ""
            competencia = regras.competencia(contexto.instante)
            ja_emitidos = uow.repositorio(RepositorioEmissao).do_mes(paciente_id, competencia, modelo.value)
            if ja_emitidos and not confirmar_reemissao:  # RF-805: aviso, sem bloqueio
                raise ConfirmacaoNecessaria("extra.emitido_no_mes", {"emissoes": ja_emitidos})
        versao, arquivo = arquivo_ativo(uow, modelo)
        permitidas = nomes(modelo)
        return _Preparo(versao, arquivo, {n: v for n, v in valores.items() if n in permitidas}, comuns.logotipo,
                        referencia)  # fmt: skip

    def _comuns(self, uow: UnidadeDeTrabalho, contexto: Contexto) -> comum.Comuns:
        comuns = comum.ler(uow, self._referencias, self._auditoria, contexto.instante)
        if not comuns.configurada:
            raise RegraViolada("instituicao.ausente")  # RF-802: sem cabeçalho, o documento não sai
        return comuns

    def _converter(self, modelo: Modelo, preparo: _Preparo, imagens: dict[str, bytes]) -> bytes:
        permitidas = nomes(modelo)
        todas: dict[str, bytes | None] = {"logotipo": preparo.logotipo, **imagens}
        docx = preencher(preparo.arquivo, preparo.valores, {n: i for n, i in todas.items() if n in permitidas})
        return self._conversor.para_pdf(docx)

    def _ficha(self, contexto: Contexto, paciente_id: int) -> DocumentoEmitido:
        """DOC-01 (DD-106): a ficha do MOD-02, que audita a leitura, em lista só com o preenchido."""
        dados = self._pacientes.ver_ficha(contexto, paciente_id)
        comuns = self._executar(lambda uow: self._comuns(uow, contexto))
        conteudo = pdf.html("ficha.html", {
            **comuns.valores, "titulo": TITULO_FICHA, "logotipo": pdf.imagem_embutida(comuns.logotipo),
            "secoes": ficha.secoes(dados),
        })  # fmt: skip
        pdf_gerado = pdf.para_pdf(conteudo)
        self._registrar(contexto, Documento.FICHA.value, 0, paciente_id, None)
        return DocumentoEmitido(pdf_gerado, _nome_arquivo(Documento.FICHA.value, contexto))

    def _registrar(
        self, contexto: Contexto, modelo: str, versao: int, paciente_id: int, referencia: str | None
    ) -> None:
        if contexto.usuario_id is None:
            raise AcessoNegado()
        emissao = DadosEmissao(paciente_id, modelo, versao, referencia, regras.competencia(contexto.instante),
                               contexto.instante, contexto.usuario_id)  # fmt: skip
        operacao = "emissao.cracha.emitir" if modelo == Modelo.CRACHA.value else "emissao.documento.emitir"

        alteracoes: dict[str, tuple[object, object]] = {"modelo": (None, modelo), "versao_modelo": (None, versao)}
        if referencia is not None:
            alteracoes["referencia"] = (None, referencia)

        def gravar(uow: UnidadeDeTrabalho) -> None:
            uow.repositorio(RepositorioEmissao).registrar(emissao)
            self._auditoria.registrar(uow, contexto, operacao, "paciente", str(paciente_id), alteracoes)

        self._executar(gravar)


def _nome_arquivo(codigo: str, contexto: Contexto) -> str:
    return f"{codigo.lower()}-{regras.hoje(contexto.instante).isoformat()}.pdf"


class EmissoesRegistradasSQL:
    """Implementa a porta EmissoesRegistradas do núcleo, para a pendência de termo do MOD-03 (RF-809)."""

    def trocas_emitidas(self, uow: UnidadeDeTrabalho, troca_ids: Sequence[int]) -> set[int]:
        referencias = [f"troca:{i}" for i in troca_ids]
        emitidas = uow.repositorio(RepositorioEmissao).referencias(Modelo.TROCA.value, referencias)
        return {int(r.removeprefix("troca:")) for r in emitidas}

    def extras_emitidas(self, uow: UnidadeDeTrabalho, paciente_ids: Sequence[int]) -> set[tuple[int, str]]:
        return uow.repositorio(RepositorioEmissao).competencias(Modelo.EXTRA.value, paciente_ids)
