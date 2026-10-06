"""Relógio dos testes (PT §3): data e hora fixadas, avançadas só pelo próprio teste."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

from sar.modulo_08_dados.relogio import FUSO_CLINICA


class RelogioControlado:
    def __init__(self, instante: datetime) -> None:
        self.ajustar(instante)

    def ajustar(self, instante: datetime) -> None:
        if instante.tzinfo is None:
            raise ValueError("instante sem fuso")
        self._agora = instante.astimezone(UTC)

    def avancar(self, intervalo: timedelta) -> None:
        self._agora += intervalo

    def agora(self) -> datetime:
        return self._agora

    def hoje(self) -> date:
        return self._agora.astimezone(FUSO_CLINICA).date()
