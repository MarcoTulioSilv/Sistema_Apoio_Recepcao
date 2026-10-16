"""O que o MOD-03 oferece às portas dos outros módulos (DDS §7.8), ligado na raiz de composição (DD-02)."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date, timedelta

from sar.modulo_01_acesso.contrato import AuditService
from sar.modulo_02_cadastro.contrato import LeituraCadastro
from sar.modulo_03_operacao import dados
from sar.modulo_03_operacao.calendario import competencia
from sar.modulo_03_operacao.marcas import gravar_marcas, meses_fechados
from sar.modulo_08_dados.interfaces.operacao import PresencaGravada, RepositorioOperacao
from sar.nucleo.contexto import Contexto
from sar.nucleo.parametros import LeitorParametros
from sar.nucleo.portas import Autorizacao, ImpactoAnulacao, Impedimento, OperacaoPeriodo, Relogio
from sar.nucleo.uow import UnidadeDeTrabalho

DESDE_SEMPRE, ATE_SEMPRE = date(1900, 1, 1), date(9999, 12, 31)


class VerificadorUsoImplantacao:
    """A data de implantação trava a partir da primeira sessão confirmada (DD-51)."""

    parametro = "data_implantacao"

    def em_uso(self, uow: UnidadeDeTrabalho) -> bool:
        return uow.repositorio(RepositorioOperacao).alguma_confirmada()


class VerificadorImpedimentoOperacao:
    """Encerramento de período (DD-31, P-08): presença depois da data impede; trocas e extras planejadas depois
    dela são canceladas na mesma transação, com registro. Alocações terminam com o período (DD-27)."""

    def __init__(self, auditoria: AuditService) -> None:
        self._auditoria = auditoria

    def impedimentos(
        self, uow: UnidadeDeTrabalho, paciente_id: int, data: date, operacao: OperacaoPeriodo
    ) -> list[Impedimento]:
        depois = [
            p
            for p in uow.repositorio(RepositorioOperacao).presencas([paciente_id], data + timedelta(days=1), ATE_SEMPRE)
            if p.situacao == "presente"
        ]
        if not depois:
            return []
        datas = tuple(sorted({p.data for p in depois}))
        return [Impedimento("presenca_posterior", "Há presença registrada depois da data do evento.", datas)]

    def ao_encerrar(self, uow: UnidadeDeTrabalho, contexto: Contexto, paciente_id: int, data: date) -> None:
        repositorio = uow.repositorio(RepositorioOperacao)
        depois = data + timedelta(days=1)
        motivo = f"Período encerrado em {data:%d/%m/%Y}"
        for troca in repositorio.trocas([paciente_id], depois, ATE_SEMPRE):
            repositorio.cancelar_troca(troca.id, contexto.instante, motivo)
            self._auditoria.registrar(
                uow, contexto, "operacao.troca.cancelar", "troca_pontual", str(troca.id), {"cancelada": (False, True)},
                motivo,
            )  # fmt: skip
        for extra in repositorio.extras([paciente_id], depois, ATE_SEMPRE):
            repositorio.cancelar_extra(extra.id, contexto.instante, motivo)
            self._auditoria.registrar(
                uow, contexto, "operacao.extra.cancelar", "extra_planejada", str(extra.id),
                {"cancelada": (False, True)}, motivo,
            )  # fmt: skip


class ParticipanteAnulacaoOperacao:
    """Anulação (§6.9, DEC-61): descarta presenças, alocações, trocas, extras, ligações, ciências e termos do
    cadastro; informa antes quantos e se alcança sessão confirmada; grava a marca se alcançar mês fechado."""

    def __init__(
        self, auditoria: AuditService, leitura: LeituraCadastro, parametros: LeitorParametros, relogio: Relogio
    ) -> None:
        self._auditoria = auditoria
        self._leitura = leitura
        self._parametros = parametros
        self._relogio = relogio

    def impacto(self, uow: UnidadeDeTrabalho, paciente_id: int) -> ImpactoAnulacao:
        contagens = self._contagens(uow, paciente_id)
        confirmadas = self._confirmadas(uow, paciente_id)
        agora = Contexto.sistema("anulacao.impacto", self._relogio.agora())
        fechados = meses_fechados(uow, dados.implantacao(self._parametros), confirmadas, agora)
        return ImpactoAnulacao({k: v for k, v in contagens.items() if v}, bool(confirmadas), bool(fechados))

    def descartar(self, uow: UnidadeDeTrabalho, contexto: Contexto, paciente_id: int, autorizacao: Autorizacao) -> None:
        contagens = {k: v for k, v in self._contagens(uow, paciente_id).items() if v}
        fechados = meses_fechados(
            uow, dados.implantacao(self._parametros), self._confirmadas(uow, paciente_id), contexto
        )
        periodos = [p.id for p in self._leitura.periodos_de(uow, [paciente_id]).get(paciente_id, [])]
        uow.repositorio(RepositorioOperacao).remover_do_paciente(paciente_id, periodos)
        if contagens:
            self._auditoria.registrar(
                uow, contexto, "operacao.paciente.descartar", "paciente", str(paciente_id),
                {chave: (quantidade, 0) for chave, quantidade in contagens.items()},
                autorizador_id=autorizacao.autorizador_id,
            )  # fmt: skip
        gravar_marcas(uow, fechados, contexto, autorizacao)

    def _contagens(self, uow: UnidadeDeTrabalho, paciente_id: int) -> dict[str, int]:
        periodos = [p.id for p in self._leitura.periodos_de(uow, [paciente_id]).get(paciente_id, [])]
        return uow.repositorio(RepositorioOperacao).contagens_do_paciente(paciente_id, periodos)

    @staticmethod
    def _confirmadas(uow: UnidadeDeTrabalho, paciente_id: int) -> list[str]:
        """As competências das presenças do paciente em sessão confirmada."""
        repositorio = uow.repositorio(RepositorioOperacao)
        presencas: list[PresencaGravada] = repositorio.presencas([paciente_id], DESDE_SEMPRE, ATE_SEMPRE)
        if not presencas:
            return []
        sessoes = repositorio.sessoes(min(p.data for p in presencas), max(p.data for p in presencas))
        confirmadas = {s.id for s in sessoes if s.confirmada_em is not None}
        return sorted({competencia(p.data) for p in presencas if p.sessao_id in confirmadas})


class AlocacaoDaFicha:
    """Para a situação da ficha (§6.3): em tratamento e com escala vigente, ou em tratamento sem alocação."""

    def __init__(self, leitura: LeituraCadastro) -> None:
        self._leitura = leitura

    def alocados(self, uow: UnidadeDeTrabalho, paciente_ids: Sequence[int], data: date) -> set[int]:
        if not paciente_ids:
            return set()
        por_paciente = dados.periodos_de(uow, self._leitura, paciente_ids, dados.escalas(uow))
        alocados = set()
        for paciente_id, (periodos, _) in por_paciente.items():
            periodo = next((p for p in periodos if p.contem(data)), None)
            if periodo is not None and periodo.escala_em(data) is not None:
                alocados.add(paciente_id)
        return alocados
