"""Modelos de documento e emissões do MOD-05 (DDS §9.5)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol


@dataclass(frozen=True, slots=True)
class DadosVersaoModelo:
    codigo: str
    versao: int
    hash_sha256: str
    enviado_em: datetime
    enviado_por: int
    ativo: bool
    ativado_em: datetime | None


@dataclass(frozen=True, slots=True)
class DadosEmissao:
    paciente_id: int
    modelo: str
    versao_modelo: int
    referencia: str | None
    competencia: str  # AAAA-MM, data local da emissão
    emitido_em: datetime
    emitido_por: int


class RepositorioModelo(Protocol):
    def versoes(self, codigo: str) -> list[DadosVersaoModelo]:
        """Da mais nova à mais antiga."""
        ...

    def arquivo(self, codigo: str, versao: int) -> bytes | None: ...

    def ativo(self, codigo: str) -> DadosVersaoModelo | None:
        """A versão enviada e ativa; None quando vale a versão 0 (DD-103)."""
        ...

    def travar(self, codigo: str) -> None:
        """Serializa envio e ativação do mesmo código: trava as versões existentes."""
        ...

    def criar(self, codigo: str, versao: int, arquivo: bytes, hash_sha256: str, em: datetime, por: int) -> None: ...

    def ativar(self, codigo: str, versao: int | None, em: datetime, por: int) -> None:
        """Desativa a ativa e ativa a versão; None só desativa (volta à versão 0)."""
        ...


class RepositorioEmissao(Protocol):
    def registrar(self, emissao: DadosEmissao) -> None: ...

    def do_mes(self, paciente_id: int, competencia: str, modelo: str) -> int:
        """Quantas emissões do modelo o paciente teve na competência (aviso do DOC-07, RF-805)."""
        ...
