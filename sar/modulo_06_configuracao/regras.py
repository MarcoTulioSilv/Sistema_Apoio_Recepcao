"""Regras puras do MOD-06: parâmetros (DD-48: tipo, limites e a forma de texto gravada no banco) e dados de
referência (DDS §10.2)."""

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


UFS = frozenset(
    {"AC", "AL", "AM", "AP", "BA", "CE", "DF", "ES", "GO", "MA", "MG", "MS", "MT", "PA", "PB", "PE", "PI", "PR",
     "RJ", "RN", "RO", "RR", "RS", "SC", "SE", "SP", "TO"}
)  # fmt: skip
MINIMO_BUSCA_MUNICIPIO = 2
LIMITE_BUSCA_MUNICIPIO = 20


def validar_nome_convenio(nome: str) -> str:
    """Espaços repetidos e das pontas saem; de 2 a 100 caracteres (coluna da 0001)."""
    limpo = " ".join(nome.split())
    if not 2 <= len(limpo) <= 100:
        raise RegraViolada("convenio.nome")
    return limpo


def validar_uf(uf: str) -> str:
    sigla = uf.strip().upper()
    if sigla not in UFS:
        raise RegraViolada("municipio.uf")
    return sigla


def termo_de_busca(termo: str) -> str | None:
    """O termo sem espaços repetidos; None se curto demais para buscar."""
    limpo = " ".join(termo.split())
    return limpo if len(limpo) >= MINIMO_BUSCA_MUNICIPIO else None
