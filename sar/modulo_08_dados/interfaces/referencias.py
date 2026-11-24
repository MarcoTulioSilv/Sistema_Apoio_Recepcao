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

    def com_prefixo(self, prefixo: str) -> list[DadosMunicipio]:
        """Os códigos de 7 dígitos que começam pelo prefixo (DD-53: o de 6 dígitos tem no máximo um)."""
        ...

    def da_uf(self, uf: str) -> list[DadosMunicipio]:
        """Todos os da UF, em ordem de nome (Goiás tem 246)."""
        ...

    def buscar(self, termo: str, uf: str | None, limite: int) -> list[DadosMunicipio]:
        """Nomes que começam pelo termo, sem distinção de caixa nem de acento, em ordem de nome."""
        ...


@dataclass(frozen=True, slots=True)
class DadosInstituicao:
    nome: str
    endereco: str
    cep: str
    municipio: str
    uf: str
    telefone: str | None
    cnpj: str | None
    tem_logotipo: bool


@dataclass(frozen=True, slots=True)
class DadosFaixaEtaria:
    inicio: int
    fim: int | None
    rotulo: str


class RepositorioInstituicao(Protocol):
    """A linha única da instituição (§10.4)."""

    def obter(self, travar: bool = False) -> DadosInstituicao | None: ...

    def gravar(self, dados: DadosInstituicao) -> None:
        """Cria a linha na primeira vez; depois altera. O logotipo não muda por aqui."""
        ...

    def gravar_logotipo(self, png: bytes) -> None: ...

    def logotipo(self) -> bytes | None: ...

    def faixas_etarias(self) -> list[DadosFaixaEtaria]:
        """Em ordem de início."""
        ...
