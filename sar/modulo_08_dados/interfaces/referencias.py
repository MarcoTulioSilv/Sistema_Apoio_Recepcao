"""Dados de referência do MOD-06 (DDS §10.2): convênios e municípios."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True, slots=True)
class DadosConvenio:
    id: int
    nome: str
    ativo: bool


@dataclass(frozen=True, slots=True)
class DadosMunicipio:
    codigo: str
    nome: str
    uf: str


class RepositorioConvenio(Protocol):
    def listar(self) -> list[DadosConvenio]:
        """Todos, em ordem de nome."""
        ...

    def por_id(self, id: int, travar: bool = False) -> DadosConvenio | None: ...

    def por_nome(self, nome: str) -> DadosConvenio | None:
        """Pela collation da coluna: sem distinção de caixa nem de acento, como a restrição de unicidade."""
        ...

    def criar(self, nome: str) -> int: ...

    def alterar(self, id: int, nome: str, ativo: bool) -> None: ...


class RepositorioMunicipio(Protocol):
    def por_codigo(self, codigo: str) -> DadosMunicipio | None: ...

    def buscar(self, termo: str, uf: str | None, limite: int) -> list[DadosMunicipio]:
        """Nomes que começam pelo termo, sem distinção de caixa nem de acento, em ordem de nome."""
        ...
