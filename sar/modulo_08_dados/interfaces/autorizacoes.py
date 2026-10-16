"""Solicitações de autorização (DDS §5.3, DEC-42). O id é aleatório (aparece em URL, §3.6), em hexadecimal."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Protocol


@dataclass(frozen=True, slots=True)
class DadosSolicitacao:
    id: str  # 32 hexadecimais
    tipo: str
    entidade: str
    entidade_id: str
    parametros: Mapping[str, Any]
    versao_alvo: int | None
    motivo: str
    solicitante_id: int
    solicitada_em: datetime
    estado: str
    decisor_id: int | None
    decidida_em: datetime | None
    motivo_decisao: str | None


class RepositorioAutorizacao(Protocol):
    def criar(self, solicitacao: DadosSolicitacao) -> None: ...

    def por_id(self, id: str) -> DadosSolicitacao | None: ...

    def travar(self, id: str) -> DadosSolicitacao | None:
        """Lê com a linha travada até o commit: duas decisões da mesma solicitação se serializam."""
        ...

    def decidir(self, id: str, estado: str, decisor_id: int | None, em: datetime, motivo: str | None) -> None: ...

    def listar(self, estado: str | None = None, solicitante_id: int | None = None) -> list[DadosSolicitacao]:
        """Da mais antiga para a mais nova: a fila de pendentes atende primeiro quem espera há mais tempo."""
        ...

    def finalizadas(self, limite: int, solicitante_id: int | None = None) -> list[DadosSolicitacao]:
        """As que já saíram de pendente, da decisão mais recente para a mais antiga."""
        ...
