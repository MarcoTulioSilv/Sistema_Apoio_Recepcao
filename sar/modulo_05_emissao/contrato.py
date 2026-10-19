"""Contrato do MOD-05 Emissão e relatórios (DDS §10): a única parte importável de fora do módulo. Por ora, só o
lembrete dos aniversariantes da tela inicial (RF-909); o resto do módulo chega no Incremento 5."""

from __future__ import annotations

from datetime import date
from typing import Protocol

from sar.nucleo.contexto import Contexto


class RelatorioService(Protocol):
    def aniversariantes(self, contexto: Contexto, data: date) -> list[str]:
        """Os nomes dos pacientes em tratamento que fazem aniversário na data; só na tela inicial, não exportável
        (§10, RF-909). Sem registro na trilha (§4.5). AcessoNegado para quem não é recepção nem administração."""
        ...
