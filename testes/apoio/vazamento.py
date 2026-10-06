"""CT-LOG-01 (PT §4.8, RNF-624): captura todo log escrito durante o teste, no formato de produção, e aponta
qualquer valor sensível gerado pela fábrica que apareça nele."""

from __future__ import annotations

import logging
from collections.abc import Iterable

from sar.nucleo.logs import FormatadorJson


class ColetorLogs(logging.Handler):
    def __init__(self) -> None:
        super().__init__(level=logging.DEBUG)
        self.setFormatter(FormatadorJson("teste"))
        self.linhas: list[str] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.linhas.append(self.format(record))


def vazamentos(linhas: Iterable[str], valores: Iterable[str]) -> list[str]:
    """As linhas que contêm algum dos valores."""
    procurados = [v for v in valores if v]
    return [linha for linha in linhas if any(v in linha for v in procurados)]
