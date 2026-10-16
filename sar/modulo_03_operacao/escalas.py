"""Escalas da enfermagem (DDS §7.1, §7.7; RF-401 a RF-406): alocação, troca pontual e extra planejada."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, timedelta

from sar.modulo_01_acesso.contrato import AuditService, AutorizacaoService, PermissionGuard
from sar.modulo_02_cadastro.contrato import LeituraCadastro, PeriodoRef
from sar.modulo_03_operacao import dados
from sar.modulo_03_operacao.calendario import competencia
from sar.modulo_03_operacao.contrato import ContagemEscalas, Escala
from sar.modulo_08_dados.interfaces.operacao import AlocacaoGravada, RepositorioOperacao
from sar.modulo_08_dados.relogio import FUSO_CLINICA
from sar.nucleo.contexto import Contexto
from sar.nucleo.erros import AcessoNegado, NaoEncontrado, RegraViolada, RequerAutorizacao
from sar.nucleo.parametros import LeitorParametros
from sar.nucleo.uow import ExecutorDeOperacao, UnidadeDeTrabalho

GUARDA = PermissionGuard()
REABRIR = "operacao.sessao.reabrir"
RETROATIVA = "operacao.alocacao.registrar_retroativa"
CANCELAR_REALIZADA = "operacao.troca.cancelar_realizada"


def _vigente(vigencias: Sequence[AlocacaoGravada], data: date) -> AlocacaoGravada | None:
    anteriores = [v for v in vigencias if v.vigencia_inicio <= data]
    return max(anteriores, key=lambda v: v.vigencia_inicio) if anteriores else None


@dataclass(frozen=True, slots=True)
class _Situacao:
    """O que o serviço precisa saber do paciente numa data."""

    periodo: PeriodoRef
    vigencias: list[AlocacaoGravada]

    def escala_em(self, data: date) -> int | None:
        vigente = _vigente(self.vigencias, data)
        return vigente.escala_id if vigente is not None else None


class RegistroEscalas:
    """A gravação de alocação e de cancelamento de troca, comum ao serviço e aos executores das versões autorizadas
    (como os executores do MOD-02 usam as regras do evento)."""

    def __init__(self, auditoria: AuditService, leitura: LeituraCadastro) -> None:
        self._auditoria = auditoria
        self._leitura = leitura

    def gravar_alocacao(
        self,
        uow: UnidadeDeTrabalho,
        contexto: Contexto,
        paciente_id: int,
        escala_id: int | None,
        inicio: date,
        variante: str = "registrar",
        autorizador_id: int | None = None,
    ) -> tuple[date, date] | None:
        """Também o executor da alocação retroativa, já autorizada (autorizador_id preenchido). Devolve o trecho de
        datas que a mudança alcança, para o executor conferir os meses fechados; None se nada mudou."""
        por_id = dados.escalas(uow)
        if escala_id is not None and escala_id not in por_id:
            raise RegraViolada("escala.inexistente")
        situacao = self.situacao(uow, paciente_id, inicio, codigo_sem_periodo="INV-03")
        anterior = situacao.escala_em(inicio)
        if anterior == escala_id:
            return None  # a mesma escala já vale: nada é gravado nem auditado (DD-10)
        seguintes = [v.vigencia_inicio for v in situacao.vigencias if v.vigencia_inicio > inicio]
        fim = min([d - timedelta(days=1) for d in seguintes[:1]] + [situacao.periodo.fim or date.max])
        if autorizador_id is None and self._alguma_confirmada(
            uow, inicio, fim, {anterior, escala_id} - {None}, contexto
        ):
            raise RequerAutorizacao(RETROATIVA)
        repositorio = uow.repositorio(RepositorioOperacao)
        alocacao_id = repositorio.gravar_alocacao(situacao.periodo.id, escala_id, inicio)

        def codigo(e: int | None) -> str | None:
            return por_id[e].codigo if e is not None else None

        operacao = RETROATIVA if autorizador_id is not None else f"operacao.alocacao.{variante}"
        self._auditoria.registrar(
            uow, contexto, operacao, "alocacao", str(alocacao_id),
            {"paciente_id": (None, paciente_id), "periodo_id": (None, situacao.periodo.id),
             "vigencia_inicio": (None, inicio), "escala": (codigo(anterior), codigo(escala_id))},
            autorizador_id=autorizador_id,
        )  # fmt: skip
        return inicio, fim

    def gravar_cancelamento_troca(
        self,
        uow: UnidadeDeTrabalho,
        contexto: Contexto,
        troca_id: int,
        motivo: str | None,
        autorizador_id: int | None = None,
    ) -> None:
        """Também o executor do cancelamento da troca já realizada (autorizador_id preenchido)."""
        repositorio = uow.repositorio(RepositorioOperacao)
        troca = repositorio.troca_por_id(troca_id, travar=True)
        if troca is None or troca.cancelada_em is not None:
            raise NaoEncontrado()
        if autorizador_id is None:
            escala_origem = self._escala_na_data(uow, troca.paciente_id, troca.data_origem)
            realizada = self.confirmada(uow, troca.data_destino, troca.escala_destino_id) or (
                escala_origem is not None and self.confirmada(uow, troca.data_origem, escala_origem)
            )
            if realizada:
                raise RequerAutorizacao(CANCELAR_REALIZADA)
        limpo = _motivo(motivo)
        repositorio.cancelar_troca(troca_id, contexto.instante, limpo)
        operacao = CANCELAR_REALIZADA if autorizador_id is not None else "operacao.troca.cancelar"
        self._auditoria.registrar(
            uow, contexto, operacao, "troca_pontual", str(troca_id), {"cancelada": (False, True)}, limpo,
            autorizador_id,
        )  # fmt: skip

    def situacao(
        self, uow: UnidadeDeTrabalho, paciente_id: int, data: date, codigo_sem_periodo: str = "INV-04"
    ) -> _Situacao:
        if self._leitura.identificacao(uow, paciente_id) is None:
            raise NaoEncontrado()
        obito = self._leitura.data_obito(uow, paciente_id)
        if obito is not None and data > obito:
            raise RegraViolada("INV-01")
        periodo = self._leitura.periodo_aberto_em(uow, paciente_id, data)
        if periodo is None:
            raise RegraViolada(codigo_sem_periodo)
        return _Situacao(periodo, uow.repositorio(RepositorioOperacao).alocacoes([periodo.id]))

    def _escala_na_data(self, uow: UnidadeDeTrabalho, paciente_id: int, data: date) -> int | None:
        periodo = self._leitura.periodo_aberto_em(uow, paciente_id, data)
        if periodo is None:
            return None
        return _Situacao(periodo, uow.repositorio(RepositorioOperacao).alocacoes([periodo.id])).escala_em(data)

    @staticmethod
    def confirmada(uow: UnidadeDeTrabalho, data: date, escala_id: int) -> bool:
        sessao = uow.repositorio(RepositorioOperacao).sessao(data, escala_id)
        return sessao is not None and sessao.confirmada_em is not None

    @staticmethod
    def _alguma_confirmada(
        uow: UnidadeDeTrabalho, inicio: date, fim: date, escalas: set[int | None], contexto: Contexto
    ) -> bool:
        """Sessão confirmada das escalas afetadas entre as datas; sessão só se confirma no próprio dia (DD-32)."""
        hoje = contexto.instante.astimezone(FUSO_CLINICA).date()
        if not escalas or inicio > hoje:
            return False
        sessoes = uow.repositorio(RepositorioOperacao).sessoes(inicio, min(fim, hoje))
        return any(s.confirmada_em is not None and s.escala_id in escalas for s in sessoes)


class ServicoEscalas:
    def __init__(
        self,
        executar: ExecutorDeOperacao,
        auditoria: AuditService,
        leitura: LeituraCadastro,
        parametros: LeitorParametros,
        autorizacoes: AutorizacaoService,
    ) -> None:
        self._executar = executar
        self._auditoria = auditoria
        self._leitura = leitura
        self._parametros = parametros
        self._autorizacoes = autorizacoes
        self._registro = RegistroEscalas(auditoria, leitura)

    # ---------------------------------------------------------------- consulta
    def escalas(self, contexto: Contexto) -> list[Escala]:
        GUARDA.exigir(contexto, "operacao.escala.consultar")
        return list(self._executar(dados.escalas).values())

    def contagem(self, contexto: Contexto, data: date) -> ContagemEscalas:
        GUARDA.exigir(contexto, "operacao.escala.consultar")

        def operacao(uow: UnidadeDeTrabalho) -> ContagemEscalas:
            por_id = dados.escalas(uow)
            ativos = self._leitura.pacientes_com_periodo_aberto_em(uow, data)
            contagem = dict.fromkeys(por_id, 0)
            sem = 0
            for periodos, _ in dados.periodos_de(uow, self._leitura, ativos, por_id).values():
                periodo = next((p for p in periodos if p.contem(data)), None)
                escala = periodo.escala_em(data) if periodo is not None else None
                if escala is None:
                    sem += 1
                else:
                    contagem[escala.id] += 1
            return ContagemEscalas(contagem, sem)

        return self._executar(operacao)

    # ---------------------------------------------------------------- alocação (RF-402, RF-405, DD-27)
    def alocar(self, contexto: Contexto, paciente_id: int, escala_id: int | None, inicio: date) -> None:
        GUARDA.exigir(contexto, "operacao.alocacao.registrar")
        self._executar(lambda uow: self._registro.gravar_alocacao(uow, contexto, paciente_id, escala_id, inicio))

    def alocar_em_lote(self, contexto: Contexto, alocacoes: Sequence[tuple[int, int | None]], inicio: date) -> None:
        GUARDA.exigir(contexto, "operacao.alocacao.registrar_em_lote")

        def operacao(uow: UnidadeDeTrabalho) -> None:
            for paciente_id, escala_id in alocacoes:
                try:
                    self._registro.gravar_alocacao(uow, contexto, paciente_id, escala_id, inicio, "registrar_em_lote")
                except RegraViolada as erro:
                    raise RegraViolada(erro.codigo, {**erro.detalhe, "paciente_id": paciente_id}) from None
                except NaoEncontrado:
                    raise RegraViolada("paciente.inexistente", {"paciente_id": paciente_id}) from None

        self._executar(operacao)

    def solicitar_alocacao_retroativa(
        self, contexto: Contexto, paciente_id: int, escala_id: int | None, inicio: date, motivo: str
    ) -> str:
        if not GUARDA.solicitavel(contexto, RETROATIVA):
            raise AcessoNegado()
        self._executar(lambda uow: self._registro.situacao(uow, paciente_id, inicio, codigo_sem_periodo="INV-03"))
        parametros = {"paciente_id": paciente_id, "escala_id": escala_id, "inicio": inicio.isoformat()}
        return self._autorizacoes.solicitar(contexto, RETROATIVA, str(paciente_id), parametros, motivo)

    # ---------------------------------------------------------------- troca pontual (RF-503, P-10, P-11)
    def registrar_troca(
        self, contexto: Contexto, paciente_id: int, origem: date, destino: date, escala_destino_id: int
    ) -> int:
        GUARDA.exigir(contexto, "operacao.troca.registrar")
        if competencia(origem) != competencia(destino):
            raise RegraViolada("P-11")

        def operacao(uow: UnidadeDeTrabalho) -> int:
            por_id = dados.escalas(uow)
            escala = por_id.get(escala_destino_id)
            if escala is None:
                raise RegraViolada("escala.inexistente")
            self._antes_da_implantacao(min(origem, destino))
            na_origem = self._registro.situacao(uow, paciente_id, origem)
            escala_origem = na_origem.escala_em(origem)
            if escala_origem is None or not por_id[escala_origem].atende(origem):
                raise RegraViolada("troca.origem_fora_da_escala")
            no_destino = self._registro.situacao(uow, paciente_id, destino)
            if not escala.atende(destino):
                raise RegraViolada("sessao.inexistente")
            if no_destino.escala_em(destino) == escala.id:
                raise RegraViolada("troca.destino_na_propria_escala")
            if self._registro.confirmada(uow, origem, escala_origem) or self._registro.confirmada(
                uow, destino, escala.id
            ):
                raise RequerAutorizacao(REABRIR)
            troca_id = uow.repositorio(RepositorioOperacao).criar_troca(paciente_id, origem, destino, escala.id)
            self._auditoria.registrar(
                uow, contexto, "operacao.troca.registrar", "troca_pontual", str(troca_id),
                {"paciente_id": (None, paciente_id), "data_origem": (None, origem), "data_destino": (None, destino),
                 "escala_destino": (None, escala.codigo)},
            )  # fmt: skip
            return troca_id

        return dados.com_restricoes(lambda: self._executar(operacao))

    def cancelar_troca(self, contexto: Contexto, troca_id: int, motivo: str | None = None) -> None:
        GUARDA.exigir(contexto, "operacao.troca.cancelar")
        self._executar(lambda uow: self._registro.gravar_cancelamento_troca(uow, contexto, troca_id, motivo))

    def solicitar_cancelamento_troca(self, contexto: Contexto, troca_id: int, motivo: str) -> str:
        if not GUARDA.solicitavel(contexto, CANCELAR_REALIZADA):
            raise AcessoNegado()
        troca = self._executar(lambda uow: uow.repositorio(RepositorioOperacao).troca_por_id(troca_id))
        if troca is None or troca.cancelada_em is not None:
            raise NaoEncontrado()
        return self._autorizacoes.solicitar(contexto, CANCELAR_REALIZADA, str(troca_id), {"troca_id": troca_id}, motivo)

    # ---------------------------------------------------------------- extra planejada (RF-504)
    def registrar_extra(self, contexto: Contexto, paciente_id: int, data: date, escala_id: int) -> int:
        GUARDA.exigir(contexto, "operacao.extra.registrar")

        def operacao(uow: UnidadeDeTrabalho) -> int:
            escala = dados.escalas(uow).get(escala_id)
            if escala is None:
                raise RegraViolada("escala.inexistente")
            self._antes_da_implantacao(data)
            situacao = self._registro.situacao(uow, paciente_id, data)
            if not escala.atende(data):
                raise RegraViolada("sessao.inexistente")
            if situacao.escala_em(data) == escala.id:
                raise RegraViolada("extra.na_propria_escala")
            if self._registro.confirmada(uow, data, escala.id):
                raise RequerAutorizacao(REABRIR)
            extra_id = uow.repositorio(RepositorioOperacao).criar_extra(paciente_id, data, escala.id)
            self._auditoria.registrar(
                uow, contexto, "operacao.extra.registrar", "extra_planejada", str(extra_id),
                {"paciente_id": (None, paciente_id), "data": (None, data), "escala": (None, escala.codigo)},
            )  # fmt: skip
            return extra_id

        return dados.com_restricoes(lambda: self._executar(operacao))

    def cancelar_extra(self, contexto: Contexto, extra_id: int, motivo: str | None = None) -> None:
        GUARDA.exigir(contexto, "operacao.extra.cancelar")

        def operacao(uow: UnidadeDeTrabalho) -> None:
            repositorio = uow.repositorio(RepositorioOperacao)
            extra = repositorio.extra_por_id(extra_id, travar=True)
            if extra is None or extra.cancelada_em is not None:
                raise NaoEncontrado()
            if self._registro.confirmada(uow, extra.data, extra.escala_id):
                raise RequerAutorizacao(REABRIR)
            limpo = _motivo(motivo)
            repositorio.cancelar_extra(extra_id, contexto.instante, limpo)
            self._auditoria.registrar(
                uow, contexto, "operacao.extra.cancelar", "extra_planejada", str(extra_id),
                {"cancelada": (False, True)}, limpo,
            )  # fmt: skip

        self._executar(operacao)

    # ---------------------------------------------------------------- apoio
    def _antes_da_implantacao(self, data: date) -> None:
        implantada = dados.implantacao(self._parametros)
        if implantada is not None and data < implantada:  # RN-05: antes dela não há sessão
            raise RegraViolada("sessao.inexistente")


def _motivo(motivo: str | None) -> str | None:
    limpo = " ".join(motivo.split()) if motivo else ""
    if len(limpo) > 300:
        raise RegraViolada("motivo.longo")
    return limpo or None
