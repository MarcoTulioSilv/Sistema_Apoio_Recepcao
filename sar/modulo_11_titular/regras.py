"""Regras puras do MOD-11: prazo derivado (DD-18), urgência da pendência 10 e o texto do desfecho."""

from __future__ import annotations

from datetime import date, timedelta

from sar.nucleo.erros import RegraViolada

DIAS_PARA_URGENCIA = 3  # §11.1, linha 10: vira urgência a 3 dias do prazo
DESFECHO_MINIMO, DESFECHO_MAXIMO = 10, 2000


def prazo(recebida_em: date, dias: int) -> date:
    """LGPD, art. 19, II: recebimento + o parâmetro titular_prazo (15 dias por padrão)."""
    return recebida_em + timedelta(days=dias)


def urgente(prazo_final: date, hoje: date) -> bool:
    return (prazo_final - hoje).days <= DIAS_PARA_URGENCIA


def texto_do_desfecho(texto: str, codigo: str) -> str:
    """Sem espaços sobrando; RegraViolada(codigo) se curto ou longo demais."""
    limpo = " ".join(texto.split())
    if not DESFECHO_MINIMO <= len(limpo) <= DESFECHO_MAXIMO:
        raise RegraViolada(codigo)
    return limpo
