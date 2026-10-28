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


class EstadoLogging:
    """O que o configurar() da DD-81 muda no processo: os handlers e o nível da raiz, a fábrica de registros e a
    captura de avisos. Teste que roda a linha de comando no próprio processo chama o configurar(); sem restaurar,
    o handler dele fica preso ao stderr capturado daquele teste, que o pytest fecha, e os testes seguintes falham
    ao escrever log ("I/O operation on closed file")."""

    def __init__(self) -> None:
        raiz = logging.getLogger()
        self._handlers = list(raiz.handlers)
        self._nivel = raiz.level
        self._fabrica = logging.getLogRecordFactory()

    def restaurar(self) -> None:
        raiz = logging.getLogger()
        for handler in list(raiz.handlers):
            raiz.removeHandler(handler)
        for handler in self._handlers:
            raiz.addHandler(handler)
        raiz.setLevel(self._nivel)
        logging.setLogRecordFactory(self._fabrica)
        logging.captureWarnings(False)
