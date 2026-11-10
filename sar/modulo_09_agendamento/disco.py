"""Job de ocupação de disco (DDS §13.1, RNF-621, DD-111): mede as pastas do servidor visíveis ao worker e devolve o
percentual da mais cheia, que fica na execução para a pendência 19 comparar com o alarme."""

from __future__ import annotations

import math
import os
import shutil
from collections.abc import Callable, Sequence
from pathlib import Path

from sar.modulo_09_agendamento.contrato import ResultadoJob
from sar.nucleo.contexto import Contexto

Medir = Callable[[Path], tuple[int, int]]  # (total, usado) em bytes


def _uso(pasta: Path) -> tuple[int, int]:
    uso = shutil.disk_usage(pasta)
    return uso.total, uso.used


def percentual(total: int, usado: int) -> int:
    """Arredondado para baixo: 84,9% ainda é 84%."""
    return math.floor(usado * 100 / total) if total > 0 else 0


def pastas_monitoradas(fixas: Sequence[Path]) -> tuple[Path, ...]:
    """As do armazenamento, mais as de SAR_DISCOS_MONITORADOS (separadas por os.pathsep), sem repetir."""
    extras = [Path(p) for p in os.environ.get("SAR_DISCOS_MONITORADOS", "").split(os.pathsep) if p.strip()]
    return tuple(dict.fromkeys([*fixas, *extras]))


class OcupacaoDisco:
    def __init__(self, pastas: Sequence[Path], medir: Medir = _uso) -> None:
        self._pastas = tuple(pastas)
        self._medir = medir

    def __call__(self, contexto: Contexto, cursor: str | None, segundos: float | None) -> ResultadoJob:
        existentes = [p for p in self._pastas if p.exists()]
        if not existentes:
            raise FileNotFoundError("nenhuma pasta monitorada")  # vira falha registrada, sem o caminho no log
        return ResultadoJob(max(percentual(*self._medir(p)) for p in existentes))
