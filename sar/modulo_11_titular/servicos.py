"""Atendimento ao titular (DDS §15, RF-1009): registro e acompanhamento dos pedidos, com prazo derivado (DD-18), e
o atendimento de acesso, que entrega num PDF só a declaração (MOD-05, DD-105), a ficha (DOC-01) e a cópia dos
documentos (MOD-04), com o registro da entrega na auditoria."""

from __future__ import annotations

import io
from datetime import date, datetime, time

import pikepdf

from sar.modulo_01_acesso.contrato import AuditService, PermissionGuard
from sar.modulo_02_cadastro.contrato import Identificacao, LeituraCadastro
from sar.modulo_04_documentos.contrato import LeituraDocumentos
from sar.modulo_05_emissao.contrato import Documento, EmissaoService
from sar.modulo_08_dados.interfaces.titular import DadosRequisicao, RepositorioTitular
from sar.modulo_08_dados.relogio import FUSO_CLINICA
from sar.modulo_11_titular import regras
from sar.modulo_11_titular.contrato import (
    Canal,
    FormaEntrega,
    PacoteTitular,
    Requisicao,
    SituacaoRequisicao,
    TipoRequisicao,
)
from sar.nucleo.contexto import Contexto
from sar.nucleo.erros import AcessoNegado, NaoEncontrado, RegraViolada
from sar.nucleo.parametros import LeitorParametros
from sar.nucleo.uow import ExecutorDeOperacao, UnidadeDeTrabalho

GUARDA = PermissionGuard()
ENTIDADE = "requisicao_titular"


def dias_do_prazo(parametros: LeitorParametros) -> int:
    dias = parametros.valor("titular_prazo")
    if not isinstance(dias, int):  # o núcleo declara em dias (DD-48)
        raise TypeError("titular_prazo")
    return dias


def hoje(contexto: Contexto) -> date:
    return contexto.instante.astimezone(FUSO_CLINICA).date()


def data_local(instante: datetime) -> date:
    return instante.astimezone(FUSO_CLINICA).date()


def requisicao(dados: DadosRequisicao, identificacao: Identificacao, dias_prazo: int, hoje_: date) -> Requisicao:
    recebida = data_local(dados.recebida_em)
    final = regras.prazo(recebida, dias_prazo)
    return Requisicao(
        dados.id, dados.paciente_id, identificacao.nome, identificacao.prontuario, TipoRequisicao(dados.tipo),
        Canal(dados.canal), recebida, SituacaoRequisicao(dados.situacao), dados.desfecho, dados.atendida_em,
        dados.atendente_id, final, (final - hoje_).days,
    )  # fmt: skip


class ServicoTitular:
    def __init__(
        self,
        executar: ExecutorDeOperacao,
        auditoria: AuditService,
        leitura: LeituraCadastro,
        parametros: LeitorParametros,
        documentos: LeituraDocumentos,
        emissao: EmissaoService,
    ) -> None:
        self._executar = executar
        self._auditoria = auditoria
        self._leitura = leitura
        self._parametros = parametros
        self._documentos = documentos
        self._emissao = emissao

    def registrar(
        self, contexto: Contexto, paciente_id: int, tipo: TipoRequisicao, canal: Canal, recebida_em: date
    ) -> int:
        GUARDA.exigir(contexto, "titular.requisicao.registrar")
        if recebida_em > hoje(contexto):
            raise RegraViolada("titular.recebida_no_futuro")
        # Guardado como instante (DATETIME UTC), ao meio-dia local da data informada: a data local nunca muda.
        instante = datetime.combine(recebida_em, time(12), FUSO_CLINICA)

        def operacao(uow: UnidadeDeTrabalho) -> int:
            if self._leitura.identificacao(uow, paciente_id) is None:
                raise NaoEncontrado()
            requisicao_id = uow.repositorio(RepositorioTitular).criar(paciente_id, tipo.value, canal.value, instante)
            self._auditoria.registrar(
                uow, contexto, "titular.requisicao.registrar", ENTIDADE, str(requisicao_id),
                {"paciente_id": (None, paciente_id), "tipo": (None, tipo.value), "canal": (None, canal.value),
                 "recebida_em": (None, recebida_em)},
            )  # fmt: skip
            return requisicao_id

        return self._executar(operacao)

    def consultar(
        self, contexto: Contexto, situacao: SituacaoRequisicao | None = SituacaoRequisicao.ABERTA
    ) -> list[Requisicao]:
        GUARDA.exigir(contexto, "titular.requisicao.consultar")
        dias = self._dias_prazo()

        def operacao(uow: UnidadeDeTrabalho) -> list[Requisicao]:
            gravadas = uow.repositorio(RepositorioTitular).listar(situacao.value if situacao else None)
            vivos = self._leitura.identificacoes(uow, sorted({g.paciente_id for g in gravadas}))
            itens = [
                requisicao(g, vivos[g.paciente_id], dias, hoje(contexto)) for g in gravadas if g.paciente_id in vivos
            ]
            # DD-10: só a quantidade vai à trilha, como na busca de pacientes.
            self._auditoria.registrar(
                uow, contexto, "titular.requisicao.consultar", ENTIDADE, None, {"quantidade": (None, len(itens))}
            )
            return itens

        return self._executar(operacao)

    def ver(self, contexto: Contexto, requisicao_id: int) -> Requisicao:
        GUARDA.exigir(contexto, "titular.requisicao.consultar")
        dias = self._dias_prazo()

        def operacao(uow: UnidadeDeTrabalho) -> Requisicao:
            dados, identificacao = self._carregar(uow, requisicao_id)
            self._auditoria.registrar(uow, contexto, "titular.requisicao.consultar", ENTIDADE, str(requisicao_id))
            return requisicao(dados, identificacao, dias, hoje(contexto))

        return self._executar(operacao)

    def atender_acesso(self, contexto: Contexto, requisicao_id: int, entrega: FormaEntrega) -> PacoteTitular:
        GUARDA.exigir(contexto, "titular.copia.gerar")

        def conferir(uow: UnidadeDeTrabalho) -> DadosRequisicao:
            dados, _ = self._carregar(uow, requisicao_id)
            if dados.situacao != SituacaoRequisicao.ABERTA:
                raise RegraViolada("titular.encerrada")
            if dados.tipo != TipoRequisicao.CONFIRMACAO_ACESSO:
                raise RegraViolada("titular.nao_e_acesso")
            return dados

        dados = self._executar(conferir)
        copia = self._documentos.copia_ao_titular(contexto, dados.paciente_id)
        with pikepdf.open(io.BytesIO(copia)) as aberta:
            paginas_documentos = len(aberta.pages)
        referencia = f"titular:{requisicao_id}"
        declaracao = self._emissao.emitir_declaracao_titular(
            contexto, dados.paciente_id, data_local(dados.recebida_em), paginas_documentos, referencia
        )
        ficha = self._emissao.emitir(contexto, Documento.FICHA, dados.paciente_id)
        pacote, total = _juntar([declaracao.pdf, ficha.pdf, copia])

        def registrar_entrega(uow: UnidadeDeTrabalho) -> None:
            self._auditoria.registrar(
                uow, contexto, "titular.copia.gerar", ENTIDADE, str(requisicao_id),
                {"entrega": (None, entrega.value), "paginas": (None, total)},
            )  # fmt: skip

        self._executar(registrar_entrega)
        return PacoteTitular(pacote, f"atendimento-titular-{hoje(contexto).isoformat()}.pdf", paginas_documentos)

    def concluir(self, contexto: Contexto, requisicao_id: int, desfecho: str) -> None:
        GUARDA.exigir(contexto, "titular.requisicao.atender")
        texto = regras.texto_do_desfecho(desfecho, "titular.desfecho")
        self._encerrar(contexto, requisicao_id, SituacaoRequisicao.ATENDIDA, texto, "titular.requisicao.atender")

    def negar(self, contexto: Contexto, requisicao_id: int, fundamento: str) -> None:
        GUARDA.exigir(contexto, "titular.requisicao.negar")
        texto = regras.texto_do_desfecho(fundamento, "titular.negativa_sem_fundamento")
        self._encerrar(contexto, requisicao_id, SituacaoRequisicao.NEGADA, texto, "titular.requisicao.negar")

    # ---------------------------------------------------------------- apoio
    def _dias_prazo(self) -> int:
        return dias_do_prazo(self._parametros)

    def _carregar(
        self, uow: UnidadeDeTrabalho, requisicao_id: int, travar: bool = False
    ) -> tuple[DadosRequisicao, Identificacao]:
        dados = uow.repositorio(RepositorioTitular).por_id(requisicao_id, travar)
        identificacao = self._leitura.identificacao(uow, dados.paciente_id) if dados else None
        if dados is None or identificacao is None:
            raise NaoEncontrado()
        return dados, identificacao

    def _encerrar(
        self, contexto: Contexto, requisicao_id: int, situacao: SituacaoRequisicao, texto: str, operacao_: str
    ) -> None:
        if contexto.usuario_id is None:
            raise AcessoNegado()
        usuario_id = contexto.usuario_id

        def operacao(uow: UnidadeDeTrabalho) -> None:
            dados, _ = self._carregar(uow, requisicao_id, travar=True)
            if dados.situacao != SituacaoRequisicao.ABERTA:
                raise RegraViolada("titular.encerrada")
            repositorio = uow.repositorio(RepositorioTitular)
            repositorio.encerrar(requisicao_id, situacao.value, texto, contexto.instante, usuario_id)
            alteracoes = {"situacao": (dados.situacao, situacao.value), "desfecho": (None, texto)}
            self._auditoria.registrar(uow, contexto, operacao_, ENTIDADE, str(requisicao_id), alteracoes)

        self._executar(operacao)


def _juntar(pdfs: list[bytes]) -> tuple[bytes, int]:
    pacote = pikepdf.new()
    abertos = []
    try:
        for conteudo in pdfs:
            origem = pikepdf.open(io.BytesIO(conteudo))
            abertos.append(origem)
            pacote.pages.extend(origem.pages)
        saida = io.BytesIO()
        pacote.save(saida)
        return saida.getvalue(), len(pacote.pages)
    finally:
        for origem in abertos:
            origem.close()
