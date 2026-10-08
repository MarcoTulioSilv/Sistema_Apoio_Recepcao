"""Repositório de sessões (SQL)."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from sar.modulo_08_dados.interfaces.sessoes import DadosSessao
from sar.modulo_08_dados.modelos.acesso import SessaoUsuario


def _banco(valor: datetime) -> datetime:
    return valor.astimezone(UTC).replace(tzinfo=None)


def _dados(s: SessaoUsuario) -> DadosSessao:
    return DadosSessao(
        id=s.id,
        usuario_id=s.usuario_id,
        origem=s.origem,
        criada_em=s.criada_em.replace(tzinfo=UTC),
        ultimo_acesso=s.ultimo_acesso.replace(tzinfo=UTC),
        encerrada_em=s.encerrada_em.replace(tzinfo=UTC) if s.encerrada_em else None,
        motivo_encerramento=s.motivo_encerramento,
    )


class RepositorioSessaoSQL:
    def __init__(self, sessao: Session) -> None:
        self._s = sessao

    def por_token_hash(self, token_hash: str) -> DadosSessao | None:
        linha = self._s.scalars(select(SessaoUsuario).where(SessaoUsuario.token_hash == token_hash)).first()
        return _dados(linha) if linha is not None else None

    def criar(self, token_hash: str, usuario_id: int, origem: str, em: datetime) -> int:
        linha = SessaoUsuario(
            token_hash=token_hash, usuario_id=usuario_id, origem=origem, criada_em=_banco(em), ultimo_acesso=_banco(em)
        )
        self._s.add(linha)
        self._s.flush()
        return linha.id

    def tocar(self, id: int, em: datetime) -> None:
        self._s.execute(
            update(SessaoUsuario).where(SessaoUsuario.id == id).values(ultimo_acesso=_banco(em)),
            execution_options={"synchronize_session": False},
        )

    def encerrar(self, id: int, em: datetime, motivo: str) -> None:
        self._s.execute(
            update(SessaoUsuario)
            .where(SessaoUsuario.id == id, SessaoUsuario.encerrada_em.is_(None))
            .values(encerrada_em=_banco(em), motivo_encerramento=motivo),
            execution_options={"synchronize_session": False},
        )

    def encerrar_do_usuario(self, usuario_id: int, em: datetime, motivo: str) -> list[int]:
        ids = list(
            self._s.scalars(
                select(SessaoUsuario.id).where(
                    SessaoUsuario.usuario_id == usuario_id, SessaoUsuario.encerrada_em.is_(None)
                )
            )
        )
        for id_ in ids:
            self.encerrar(id_, em, motivo)
        return ids
