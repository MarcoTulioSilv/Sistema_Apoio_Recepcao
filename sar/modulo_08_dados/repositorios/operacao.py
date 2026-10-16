"""Repositório do MOD-03 Operação (SQL)."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, date, datetime
from typing import cast

from sqlalchemy import Select, delete, or_, select, update
from sqlalchemy.dialects.mysql import insert as mysql_insert
from sqlalchemy.orm import Session

from sar.modulo_08_dados.interfaces.operacao import (
    AlocacaoGravada,
    CienciaGravada,
    EscalaGravada,
    ExtraGravada,
    LigacaoGravada,
    PresencaGravada,
    SessaoGravada,
    SituacaoPresenca,
    TrocaGravada,
)
from sar.modulo_08_dados.modelos.operacao import (
    Alocacao,
    CienciaEnfermagem,
    Escala,
    ExtraPlanejada,
    LigacaoManual,
    Presenca,
    SessaoTurno,
    TrocaPontual,
)


def _utc(instante: datetime | None) -> datetime | None:
    return instante.replace(tzinfo=UTC) if instante is not None else None


def _gravar(instante: datetime) -> datetime:
    return instante.astimezone(UTC).replace(tzinfo=None)


def _troca(t: TrocaPontual) -> TrocaGravada:
    return TrocaGravada(t.id, t.paciente_id, t.data_origem, t.data_destino, t.escala_destino_id, t.documento_id,
                        _utc(t.cancelada_em), t.cancelada_motivo)  # fmt: skip


def _extra(e: ExtraPlanejada) -> ExtraGravada:
    return ExtraGravada(e.id, e.paciente_id, e.data, e.escala_id, _utc(e.cancelada_em), e.cancelada_motivo)


def _sessao(s: SessaoTurno) -> SessaoGravada:
    return SessaoGravada(s.id, s.data, s.escala_id, _utc(s.confirmada_em), s.confirmada_por, s.nao_realizada_motivo,
                         s.versao)  # fmt: skip


_PRESENCA = select(Presenca, SessaoTurno.data, SessaoTurno.escala_id).join(
    SessaoTurno, SessaoTurno.id == Presenca.sessao_id
)


class RepositorioOperacaoSQL:
    def __init__(self, sessao: Session) -> None:
        self._s = sessao

    # ---------------------------------------------------------------- escalas
    def escalas(self) -> list[EscalaGravada]:
        return [
            EscalaGravada(e.id, e.codigo, e.turno, e.dias, e.hora_inicio, e.hora_fim)
            for e in self._s.scalars(select(Escala).order_by(Escala.id))
        ]

    # ---------------------------------------------------------------- alocações
    def alocacoes(self, periodo_ids: Sequence[int]) -> list[AlocacaoGravada]:
        if not periodo_ids:
            return []
        consulta = (
            select(Alocacao)
            .where(Alocacao.periodo_id.in_(list(periodo_ids)))
            .order_by(Alocacao.periodo_id, Alocacao.vigencia_inicio)
        )
        return [AlocacaoGravada(a.id, a.periodo_id, a.escala_id, a.vigencia_inicio) for a in self._s.scalars(consulta)]

    def gravar_alocacao(self, periodo_id: int, escala_id: int | None, inicio: date) -> int:
        consulta = select(Alocacao).where(Alocacao.periodo_id == periodo_id, Alocacao.vigencia_inicio == inicio)
        linha = self._s.scalars(consulta.with_for_update()).one_or_none()
        if linha is None:
            linha = Alocacao(periodo_id=periodo_id, escala_id=escala_id, vigencia_inicio=inicio)
            self._s.add(linha)
        else:
            linha.escala_id = escala_id
        self._s.flush()
        return linha.id

    # ---------------------------------------------------------------- trocas
    def troca_por_id(self, id: int, travar: bool = False) -> TrocaGravada | None:
        consulta = select(TrocaPontual).where(TrocaPontual.id == id)
        linha = self._s.scalars(consulta.with_for_update() if travar else consulta).one_or_none()
        return _troca(linha) if linha is not None else None

    def trocas(self, paciente_ids: Sequence[int] | None, inicio: date, fim: date) -> list[TrocaGravada]:
        consulta = select(TrocaPontual).where(
            TrocaPontual.cancelada_em.is_(None),
            or_(TrocaPontual.data_origem.between(inicio, fim), TrocaPontual.data_destino.between(inicio, fim)),
        )
        if paciente_ids is not None:
            consulta = consulta.where(TrocaPontual.paciente_id.in_(list(paciente_ids)))
        consulta = consulta.order_by(TrocaPontual.paciente_id, TrocaPontual.data_origem, TrocaPontual.id)
        return [_troca(t) for t in self._s.scalars(consulta)]

    def criar_troca(self, paciente_id: int, origem: date, destino: date, escala_destino_id: int) -> int:
        linha = TrocaPontual(paciente_id=paciente_id, data_origem=origem, data_destino=destino,
                             escala_destino_id=escala_destino_id)  # fmt: skip
        self._s.add(linha)
        self._s.flush()
        return linha.id

    def cancelar_troca(self, id: int, em: datetime, motivo: str | None) -> None:
        self._s.execute(
            update(TrocaPontual).where(TrocaPontual.id == id).values(cancelada_em=_gravar(em), cancelada_motivo=motivo),
            execution_options={"synchronize_session": False},
        )

    # ---------------------------------------------------------------- extras
    def extra_por_id(self, id: int, travar: bool = False) -> ExtraGravada | None:
        consulta = select(ExtraPlanejada).where(ExtraPlanejada.id == id)
        linha = self._s.scalars(consulta.with_for_update() if travar else consulta).one_or_none()
        return _extra(linha) if linha is not None else None

    def extras(self, paciente_ids: Sequence[int] | None, inicio: date, fim: date) -> list[ExtraGravada]:
        consulta = select(ExtraPlanejada).where(
            ExtraPlanejada.cancelada_em.is_(None), ExtraPlanejada.data.between(inicio, fim)
        )
        if paciente_ids is not None:
            consulta = consulta.where(ExtraPlanejada.paciente_id.in_(list(paciente_ids)))
        consulta = consulta.order_by(ExtraPlanejada.paciente_id, ExtraPlanejada.data, ExtraPlanejada.escala_id)
        return [_extra(e) for e in self._s.scalars(consulta)]

    def criar_extra(self, paciente_id: int, data: date, escala_id: int) -> int:
        linha = ExtraPlanejada(paciente_id=paciente_id, data=data, escala_id=escala_id)
        self._s.add(linha)
        self._s.flush()
        return linha.id

    def cancelar_extra(self, id: int, em: datetime, motivo: str | None) -> None:
        self._s.execute(
            update(ExtraPlanejada)
            .where(ExtraPlanejada.id == id)
            .values(cancelada_em=_gravar(em), cancelada_motivo=motivo),
            execution_options={"synchronize_session": False},
        )

    # ---------------------------------------------------------------- sessões
    def sessao(self, data: date, escala_id: int, travar: bool = False) -> SessaoGravada | None:
        consulta = select(SessaoTurno).where(SessaoTurno.data == data, SessaoTurno.escala_id == escala_id)
        linha = self._s.scalars(consulta.with_for_update() if travar else consulta).one_or_none()
        return _sessao(linha) if linha is not None else None

    def criar_sessao(self, data: date, escala_id: int) -> int:
        linha = SessaoTurno(data=data, escala_id=escala_id)
        self._s.add(linha)
        self._s.flush()
        return linha.id

    def garantir_sessao(self, data: date, escala_id: int) -> SessaoGravada:
        self._s.execute(
            mysql_insert(SessaoTurno).values(data=data, escala_id=escala_id).on_duplicate_key_update(id=SessaoTurno.id)
        )
        sessao = self.sessao(data, escala_id, travar=True)
        if sessao is None:
            raise RuntimeError("sessão some logo depois de garantida")
        return sessao

    def tocar_sessao(self, id: int) -> int:
        self._s.execute(
            update(SessaoTurno).where(SessaoTurno.id == id).values(versao=SessaoTurno.versao + 1),
            execution_options={"synchronize_session": False},
        )
        return int(self._s.scalars(select(SessaoTurno.versao).where(SessaoTurno.id == id)).one())

    def sessoes(self, inicio: date, fim: date) -> list[SessaoGravada]:
        consulta = (
            select(SessaoTurno)
            .where(SessaoTurno.data.between(inicio, fim))
            .order_by(SessaoTurno.data, SessaoTurno.escala_id)
        )
        return [_sessao(s) for s in self._s.scalars(consulta)]

    def alguma_confirmada(self) -> bool:
        return self._s.scalar(select(SessaoTurno.id).where(SessaoTurno.confirmada_em.is_not(None)).limit(1)) is not None

    def confirmar_sessao(self, id: int, versao: int, em: datetime, por: int, nao_realizada: str | None) -> bool:
        resultado = self._s.execute(
            update(SessaoTurno)
            .where(SessaoTurno.id == id, SessaoTurno.versao == versao)
            .values(confirmada_em=_gravar(em), confirmada_por=por, nao_realizada_motivo=nao_realizada,
                    versao=SessaoTurno.versao + 1),
            execution_options={"synchronize_session": False},
        )  # fmt: skip
        return bool(getattr(resultado, "rowcount", 0) == 1)

    # ---------------------------------------------------------------- presenças
    @staticmethod
    def _presencas(linhas: Select[tuple[Presenca, date, int]], s: Session) -> list[PresencaGravada]:
        return [
            PresencaGravada(p.id, p.sessao_id, p.paciente_id, cast(SituacaoPresenca, p.situacao), data, escala_id)
            for p, data, escala_id in s.execute(linhas)
        ]

    def presencas_da_sessao(self, sessao_id: int) -> list[PresencaGravada]:
        return self._presencas(_PRESENCA.where(Presenca.sessao_id == sessao_id).order_by(Presenca.id), self._s)

    def presenca_por_id(self, id: int) -> PresencaGravada | None:
        encontradas = self._presencas(_PRESENCA.where(Presenca.id == id), self._s)
        return encontradas[0] if encontradas else None

    def presencas(self, paciente_ids: Sequence[int] | None, inicio: date, fim: date) -> list[PresencaGravada]:
        consulta = _PRESENCA.where(SessaoTurno.data.between(inicio, fim))
        if paciente_ids is not None:
            consulta = consulta.where(Presenca.paciente_id.in_(list(paciente_ids)))
        return self._presencas(consulta.order_by(SessaoTurno.data, SessaoTurno.escala_id, Presenca.id), self._s)

    def gravar_presenca(self, sessao_id: int, paciente_id: int, situacao: SituacaoPresenca) -> int:
        consulta = select(Presenca).where(Presenca.sessao_id == sessao_id, Presenca.paciente_id == paciente_id)
        linha = self._s.scalars(consulta.with_for_update()).one_or_none()
        if linha is None:
            linha = Presenca(sessao_id=sessao_id, paciente_id=paciente_id, situacao=situacao)
            self._s.add(linha)
        else:
            linha.situacao = situacao
        self._s.flush()
        return linha.id

    def remover_presenca(self, id: int) -> None:
        self._s.execute(
            delete(LigacaoManual).where(or_(LigacaoManual.ausencia_id == id, LigacaoManual.presenca_id == id))
        )
        self._s.execute(delete(CienciaEnfermagem).where(CienciaEnfermagem.presenca_id == id))
        self._s.execute(delete(Presenca).where(Presenca.id == id))

    # ---------------------------------------------------------------- ligações e ciências
    def ligacoes(self, presenca_ids: Sequence[int]) -> list[LigacaoGravada]:
        if not presenca_ids:
            return []
        ids = list(presenca_ids)
        consulta = (
            select(LigacaoManual)
            .where(or_(LigacaoManual.ausencia_id.in_(ids), LigacaoManual.presenca_id.in_(ids)))
            .order_by(LigacaoManual.id)
        )
        return [
            LigacaoGravada(li.id, li.ausencia_id, li.presenca_id, li.criada_por, li.criada_em.replace(tzinfo=UTC))
            for li in self._s.scalars(consulta)
        ]

    def criar_ligacao(self, ausencia_id: int, presenca_id: int, por: int, em: datetime) -> int:
        linha = LigacaoManual(ausencia_id=ausencia_id, presenca_id=presenca_id, criada_por=por, criada_em=_gravar(em))
        self._s.add(linha)
        self._s.flush()
        return linha.id

    def remover_ligacoes(self, ids: Sequence[int]) -> None:
        if ids:
            self._s.execute(delete(LigacaoManual).where(LigacaoManual.id.in_(list(ids))))

    def ciencias(self, presenca_ids: Sequence[int]) -> list[CienciaGravada]:
        if not presenca_ids:
            return []
        consulta = select(CienciaEnfermagem).where(CienciaEnfermagem.presenca_id.in_(list(presenca_ids)))
        return [
            CienciaGravada(c.presenca_id, c.registrada_em.replace(tzinfo=UTC), c.registrada_por)
            for c in self._s.scalars(consulta.order_by(CienciaEnfermagem.presenca_id))
        ]
