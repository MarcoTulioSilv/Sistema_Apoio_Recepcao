"""Repositório do rascunho de cadastro (SQL)."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from sar.modulo_08_dados.interfaces.rascunhos import RascunhoGravado
from sar.modulo_08_dados.modelos.cadastro import RascunhoCadastro

_SEM_NONCE = bytes(12)


def _banco(valor: datetime) -> datetime:
    return valor.astimezone(UTC).replace(tzinfo=None)


class RepositorioRascunhoSQL:
    def __init__(self, sessao: Session) -> None:
        self._s = sessao

    def do_usuario(self, usuario_id: int) -> RascunhoGravado | None:
        r = self._s.scalars(select(RascunhoCadastro).where(RascunhoCadastro.usuario_id == usuario_id)).one_or_none()
        if r is None:
            return None
        return RascunhoGravado(
            r.id, r.usuario_id, r.conteudo_cifrado, r.nonce, r.criado_em.replace(tzinfo=UTC),
            r.atualizado_em.replace(tzinfo=UTC),
        )  # fmt: skip

    def criar(self, usuario_id: int, em: datetime) -> int:
        linha = RascunhoCadastro(
            usuario_id=usuario_id,
            conteudo_cifrado=b"",
            nonce=_SEM_NONCE,
            criado_em=_banco(em),
            atualizado_em=_banco(em),
        )
        self._s.add(linha)
        self._s.flush()
        return linha.id

    def gravar(self, id: int, conteudo_cifrado: bytes, nonce: bytes, em: datetime) -> None:
        linha = self._s.get_one(RascunhoCadastro, id)
        linha.conteudo_cifrado, linha.nonce, linha.atualizado_em = conteudo_cifrado, nonce, _banco(em)
        self._s.flush()

    def remover_do_usuario(self, usuario_id: int) -> bool:
        resultado = self._s.execute(delete(RascunhoCadastro).where(RascunhoCadastro.usuario_id == usuario_id))
        return bool(getattr(resultado, "rowcount", 0))
