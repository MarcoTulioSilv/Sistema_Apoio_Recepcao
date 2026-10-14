"""Repositório de solicitações de autorização (SQL)."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from sar.modulo_08_dados.interfaces.autorizacoes import DadosSolicitacao
from sar.modulo_08_dados.modelos.acesso import SolicitacaoAutorizacao


def _banco(valor: datetime) -> datetime:
    return valor.astimezone(UTC).replace(tzinfo=None)


def _dados(s: SolicitacaoAutorizacao) -> DadosSolicitacao:
    return DadosSolicitacao(
        id=s.id.hex(),
        tipo=s.tipo,
        entidade=s.entidade,
        entidade_id=s.entidade_id,
        parametros=dict(s.parametros),
        versao_alvo=s.versao_alvo,
        motivo=s.motivo,
        solicitante_id=s.solicitante_id,
        solicitada_em=s.solicitada_em.replace(tzinfo=UTC),
        estado=s.estado,
        decisor_id=s.decisor_id,
        decidida_em=s.decidida_em.replace(tzinfo=UTC) if s.decidida_em else None,
        motivo_decisao=s.motivo_decisao,
    )


def _bytes(id: str) -> bytes | None:
    try:
        valor = bytes.fromhex(id)
    except ValueError:
        return None
    return valor if len(valor) == 16 else None


class RepositorioAutorizacaoSQL:
    def __init__(self, sessao: Session) -> None:
        self._s = sessao

    def criar(self, solicitacao: DadosSolicitacao) -> None:
        self._s.add(
            SolicitacaoAutorizacao(
                id=bytes.fromhex(solicitacao.id),
                tipo=solicitacao.tipo,
                entidade=solicitacao.entidade,
                entidade_id=solicitacao.entidade_id,
                parametros=dict(solicitacao.parametros),
                versao_alvo=solicitacao.versao_alvo,
                motivo=solicitacao.motivo,
                solicitante_id=solicitacao.solicitante_id,
                solicitada_em=_banco(solicitacao.solicitada_em),
                estado=solicitacao.estado,
                decisor_id=solicitacao.decisor_id,
                decidida_em=_banco(solicitacao.decidida_em) if solicitacao.decidida_em else None,
                motivo_decisao=solicitacao.motivo_decisao,
            )
        )
        self._s.flush()

    def por_id(self, id: str) -> DadosSolicitacao | None:
        chave = _bytes(id)
        linha = self._s.get(SolicitacaoAutorizacao, chave) if chave else None
        return _dados(linha) if linha is not None else None

    def travar(self, id: str) -> DadosSolicitacao | None:
        chave = _bytes(id)
        if chave is None:
            return None
        consulta = select(SolicitacaoAutorizacao).where(SolicitacaoAutorizacao.id == chave).with_for_update()
        linha = self._s.scalars(consulta.execution_options(populate_existing=True)).first()
        return _dados(linha) if linha is not None else None

    def decidir(self, id: str, estado: str, decisor_id: int | None, em: datetime, motivo: str | None) -> None:
        self._s.execute(
            update(SolicitacaoAutorizacao)
            .where(SolicitacaoAutorizacao.id == bytes.fromhex(id))
            .values(estado=estado, decisor_id=decisor_id, decidida_em=_banco(em), motivo_decisao=motivo),
            execution_options={"synchronize_session": False},
        )

    def finalizadas(self, limite: int, solicitante_id: int | None = None) -> list[DadosSolicitacao]:
        quando = func.coalesce(SolicitacaoAutorizacao.decidida_em, SolicitacaoAutorizacao.solicitada_em)
        consulta = select(SolicitacaoAutorizacao).where(SolicitacaoAutorizacao.estado != "pendente")
        if solicitante_id is not None:
            consulta = consulta.where(SolicitacaoAutorizacao.solicitante_id == solicitante_id)
        consulta = consulta.order_by(quando.desc(), SolicitacaoAutorizacao.solicitada_em.desc()).limit(limite)
        return [_dados(linha) for linha in self._s.scalars(consulta)]

    def listar(self, estado: str | None = None, solicitante_id: int | None = None) -> list[DadosSolicitacao]:
        consulta = select(SolicitacaoAutorizacao).order_by(SolicitacaoAutorizacao.solicitada_em)
        if estado is not None:
            consulta = consulta.where(SolicitacaoAutorizacao.estado == estado)
        if solicitante_id is not None:
            consulta = consulta.where(SolicitacaoAutorizacao.solicitante_id == solicitante_id)
        return [_dados(linha) for linha in self._s.scalars(consulta)]
