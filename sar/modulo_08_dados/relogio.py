"""Relógio real (DDS §3.7). Os testes usam um relógio controlado no lugar deste."""

from __future__ import annotations

from datetime import UTC, date, datetime
from zoneinfo import ZoneInfo

FUSO_CLINICA = ZoneInfo("America/Sao_Paulo")


class RelogioSistema:
    def agora(self) -> datetime:
        return datetime.now(UTC)

    def hoje(self) -> date:
        return self.agora().astimezone(FUSO_CLINICA).date()
