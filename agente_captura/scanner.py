"""O scanner visto pelo agente: uma fonte de páginas em BMP, uma por folha (§8.5). A implementação real é o WIA
(`wia.py`, só no Windows); os testes usam um scanner falso com a mesma interface."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Literal, Protocol

Papel = Literal["vidro", "alimentador"]


class SemPapel(Exception):
    """Alimentador vazio antes da primeira folha."""


class ScannerIndisponivel(Exception):
    """Scanner configurado não encontrado, desligado ou ocupado."""


class Scanner(Protocol):
    def paginas(self, papel: Papel) -> Iterator[bytes]:
        """Cada página em BMP, em tons de cinza a 300 dpi (DD-78), assim que sai do scanner. No vidro, uma página; no
        alimentador, até acabar o papel. `SemPapel` se o alimentador estiver vazio; `ScannerIndisponivel`."""
        ...
