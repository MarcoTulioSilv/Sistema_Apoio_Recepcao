"""Repositório das requisições de titular (SQL)."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from sar.modulo_08_dados.interfaces.titular import DadosRequisicao
from sar.modulo_08_dados.modelos.titular import RequisicaoTitular


def _gravar(instante: datetime) -> datetime:
    return instante.astimezone(UTC).replace(tzinfo=None)


def _dados(linha: RequisicaoTitular) -> DadosRequisicao:
    return DadosRequisicao(
        linha.id, linha.paciente_id, linha.tipo, linha.canal, linha.recebida_em.replace(tzinfo=UTC), linha.situacao,
        linha.desfecho, linha.atendida_em.replace(tzinfo=UTC) if linha.atendida_em else None, linha.atendente_id,
    )  # fmt: skip


class RepositorioTitularSQL:
    def __init__(self, sessao: Session) -> None:
        self._s = sessao

    def criar(self, paciente_id: int, tipo: str, canal: str, recebida_em: datetime) -> int:
        linha = RequisicaoTitular(paciente_id=paciente_id, tipo=tipo, canal=canal, recebida_em=_gravar(recebida_em),
                                  situacao="aberta")  # fmt: skip
        self._s.add(linha)
        self._s.flush()
        return linha.id

    def por_id(self, id: int, travar: bool = False) -> DadosRequisicao | None:
        consulta = select(RequisicaoTitular).where(RequisicaoTitular.id == id)
        linha = self._s.scalars(consulta.with_for_update() if travar else consulta).one_or_none()
        return _dados(linha) if linha is not None else None

    def listar(self, situacao: str | None) -> list[DadosRequisicao]:
        consulta = select(RequisicaoTitular).order_by(RequisicaoTitular.recebida_em, RequisicaoTitular.id)
        if situacao is not None:
            consulta = consulta.where(RequisicaoTitular.situacao == situacao)
        return [_dados(linha) for linha in self._s.scalars(consulta)]

    def encerrar(self, id: int, situacao: str, desfecho: str, em: datetime, por: int) -> None:
        linha = self._s.get_one(RequisicaoTitular, id)
        linha.situacao, linha.desfecho, linha.atendida_em, linha.atendente_id = situacao, desfecho, _gravar(em), por
        self._s.flush()
