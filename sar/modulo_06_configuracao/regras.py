"""Regras puras dos parâmetros (DD-48): tipo, limites e a forma de texto gravada no banco."""

from __future__ import annotations

from datetime import date

from sar.modulo_06_configuracao.contrato import Valor
from sar.nucleo.erros import RegraViolada
from sar.nucleo.parametros import Parametro, Unidade


def validar(parametro: Parametro, valor: Valor) -> Valor:
    """O valor no tipo da unidade e dentro dos limites; senão RegraViolada, com os limites no detalhe."""
    if parametro.unidade is Unidade.BOOLEANO:
        if not isinstance(valor, bool):
            raise RegraViolada("parametro.tipo", {"nome": parametro.nome, "esperado": "sim ou não"})
        return valor
    if parametro.unidade is Unidade.DATA:
        if not isinstance(valor, date):
            raise RegraViolada("parametro.tipo", {"nome": parametro.nome, "esperado": "data"})
        return valor
    if not isinstance(valor, int) or isinstance(valor, bool):
        raise RegraViolada("parametro.tipo", {"nome": parametro.nome, "esperado": "número inteiro"})
    if (parametro.minimo is not None and valor < parametro.minimo) or (
        parametro.maximo is not None and valor > parametro.maximo
    ):
        raise RegraViolada(
            "parametro.fora_dos_limites",
            {"nome": parametro.nome, "minimo": parametro.minimo, "maximo": parametro.maximo},
        )
    return valor


def para_texto(parametro: Parametro, valor: Valor) -> str:
    if parametro.unidade is Unidade.BOOLEANO:
        return "true" if valor else "false"
    if isinstance(valor, date):
        return valor.isoformat()
    return str(valor)


def de_texto(parametro: Parametro, texto: str) -> Valor:
    """O valor gravado, validado de novo: um limite pode ter mudado no código depois da gravação."""
    if parametro.unidade is Unidade.BOOLEANO:
        if texto not in ("true", "false"):
            raise ValueError("booleano gravado fora do formato")
        return validar(parametro, texto == "true")
    if parametro.unidade is Unidade.DATA:
        return validar(parametro, date.fromisoformat(texto))
    return validar(parametro, int(texto))
