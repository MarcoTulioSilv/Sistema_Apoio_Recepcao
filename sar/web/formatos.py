"""Formatos de tela de telefone e CEP. Só apresentação: o serviço e o banco guardam só os dígitos (DDS §6.4)."""

from __future__ import annotations


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
