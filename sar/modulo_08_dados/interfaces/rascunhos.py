"""Rascunho de cadastro (DDS §6.6): um por usuário, guardado cifrado (DD-07)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol


@dataclass(frozen=True, slots=True)
class RascunhoGravado:
    id: int
    usuario_id: int
    conteudo_cifrado: bytes
    nonce: bytes
    criado_em: datetime
    atualizado_em: datetime


class RepositorioRascunho(Protocol):
    def do_usuario(self, usuario_id: int) -> RascunhoGravado | None: ...

    def criar(self, usuario_id: int, em: datetime) -> int:
        """Linha com conteúdo vazio: o id entra no dado associado da cifra, então ela nasce antes do cifrado,
        na mesma transação em que o conteúdo é gravado."""
        ...

    def gravar(self, id: int, conteudo_cifrado: bytes, nonce: bytes, em: datetime) -> None: ...

    def remover_do_usuario(self, usuario_id: int) -> bool:
        """True se havia rascunho."""
        ...
