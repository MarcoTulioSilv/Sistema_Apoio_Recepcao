"""Formatos de tela de telefone, CEP e instante. Só apresentação: o serviço e o banco guardam os dígitos e o UTC
(DDS §6.4)."""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

FUSO = ZoneInfo("America/Sao_Paulo")


def _digitos(valor: str | None) -> str:
    return "".join(c for c in (valor or "") if c.isdigit())


def telefone(numero: str | None) -> str:
    """Celular 99999-0001 (5-4); fixo 3631-0002 (4-4). Outro tamanho volta como veio, para a pessoa ver e corrigir."""
    d = _digitos(numero)
    if len(d) == 9:
        return f"{d[:5]}-{d[5:]}"
    if len(d) == 8:
        return f"{d[:4]}-{d[4:]}"
    return numero or ""


def cep(valor: str | None) -> str:
    """75800-000 (5-3)."""
    d = _digitos(valor)
    return f"{d[:5]}-{d[5:]}" if len(d) == 8 else (valor or "")


def data_hora(instante: datetime | None) -> str:
    """13/10/2026 10:05, na hora da clínica; o serviço entrega em UTC."""
    if instante is None:
        return ""
    return instante.astimezone(FUSO).strftime("%d/%m/%Y %H:%M")
