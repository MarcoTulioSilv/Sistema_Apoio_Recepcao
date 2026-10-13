"""Valores alterados dos parâmetros (DD-48): o banco guarda só o valor, como texto; padrão, limites e editor
estão declarados no núcleo."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol


@dataclass(frozen=True, slots=True)
class ValorGravado:
    nome: str
    valor: str
    alterado_em: datetime
    alterado_por: int


class RepositorioParametro(Protocol):
    def valor(self, nome: str) -> ValorGravado | None: ...

    def todos(self) -> list[ValorGravado]: ...

    def gravar(self, nome: str, valor: str, em: datetime, por: int) -> None:
        """Cria ou substitui o valor. Não há exclusão: voltar ao padrão grava o padrão."""
        ...
