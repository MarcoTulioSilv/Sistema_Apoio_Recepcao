"""Sessões de usuário (DDS §5.1, DD-05, DD-19). O token nunca é gravado: só o SHA-256 dele."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol


@dataclass(frozen=True, slots=True)
class DadosSessao:
    id: int
    usuario_id: int
    origem: str
    criada_em: datetime
    ultimo_acesso: datetime
    encerrada_em: datetime | None
    motivo_encerramento: str | None


class RepositorioSessao(Protocol):
    def por_token_hash(self, token_hash: str) -> DadosSessao | None: ...

    def criar(self, token_hash: str, usuario_id: int, origem: str, em: datetime) -> int: ...

    def tocar(self, id: int, em: datetime) -> None:
        """Atualiza o último acesso: só requisição de pessoa, nunca a automática (DD-19, DD-57)."""
        ...

    def encerrar(self, id: int, em: datetime, motivo: str) -> None: ...

    def encerrar_do_usuario(self, usuario_id: int, em: datetime, motivo: str) -> list[int]:
        """Encerra as sessões ativas do usuário e devolve os ids encerrados."""
        ...
