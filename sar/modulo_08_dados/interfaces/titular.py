"""Requisições de titular do MOD-11 (DDS §15)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol


@dataclass(frozen=True, slots=True)
class DadosRequisicao:
    id: int
    paciente_id: int
    tipo: str
    canal: str
    recebida_em: datetime
    situacao: str
    desfecho: str | None
    atendida_em: datetime | None
    atendente_id: int | None


class RepositorioTitular(Protocol):
    def criar(self, paciente_id: int, tipo: str, canal: str, recebida_em: datetime) -> int: ...

    def por_id(self, id: int, travar: bool = False) -> DadosRequisicao | None: ...

    def listar(self, situacao: str | None) -> list[DadosRequisicao]:
        """Da mais antiga para a mais nova; todas com None."""
        ...

    def encerrar(self, id: int, situacao: str, desfecho: str, em: datetime, por: int) -> None: ...
