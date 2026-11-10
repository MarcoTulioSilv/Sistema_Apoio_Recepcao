"""Contrato do MOD-07 Pendências (DDS §11.5): a única parte importável de fora do módulo.

Pendência é consulta, sem tabela (modelo §7.4): cada linha da matriz tem uma fonte no módulo dono (DD-54), ligada
pela raiz de composição.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Protocol

from sar.modulo_07_pendencias.matriz import MATRIZ, POR_CODIGO, LinhaMatriz
from sar.nucleo.contexto import Contexto
from sar.nucleo.portas import ItemPendencia, Prioridade

__all__ = [
    "MATRIZ",
    "POR_CODIGO",
    "ContagemTipo",
    "ItemPendencia",
    "LinhaMatriz",
    "PendenciaService",
    "Prioridade",
    "Resumo",
]


@dataclass(frozen=True, slots=True)
class ContagemTipo:
    codigo: str
    nome: str
    prioridade: Prioridade
    quantidade: int


@dataclass(frozen=True, slots=True)
class Resumo:
    tipos: tuple[ContagemTipo, ...]  # urgências primeiro (RNF-408, IU-04)
    totais: Mapping[Prioridade, int]  # as três prioridades, mesmo com zero

    @property
    def total(self) -> int:
        return sum(self.totais.values())


class PendenciaService(Protocol):
    def resumo(self, contexto: Contexto) -> Resumo:
        """Contagem por tipo das linhas do perfil, para a tela inicial e o menu."""
        ...

    def listar(self, contexto: Contexto, codigo: str | None = None) -> list[ItemPendencia]:
        """Os itens do perfil, de todas as linhas ou de uma só, urgência no topo e a mais antiga primeiro. Linha que o
        perfil não vê: AcessoNegado."""
        ...

    def dos_pacientes(self, contexto: Contexto, ids: Sequence[int]) -> dict[int, list[ItemPendencia]]:
        """As pendências de paciente que o perfil vê, por paciente, numa consulta por fonte (§11.3). Usada na
        preparação do turno (DD-30) e na ficha."""
        ...
