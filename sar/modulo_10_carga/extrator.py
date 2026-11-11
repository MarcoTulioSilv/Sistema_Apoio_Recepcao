"""Leitura das planilhas da carga (AD-22): OpenPyXL em modo só leitura, sem macros e sem fórmulas recalculadas.

Só transforma células em valores (texto ou data); toda regra fica em regras.py. Nenhum valor vai para log nem para
mensagem de erro: o erro diz qual planilha falhou, nunca o que havia nela (RNF-624).
"""

from __future__ import annotations

import zipfile
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any

from openpyxl import load_workbook

from sar.modulo_10_carga.regras import (
    COLUNAS_P4,
    BlocoP1,
    CelulaP1,
    LinhaP3,
    LinhaP4,
    Valor,
    classificar_linha_p3,
    coluna_do_nome_p3,
    norm_rotulo,
)
from sar.nucleo.erros import RegraViolada

# Os nomes que o TI dá às planilhas na pasta da carga (docs/comandos.md). A P4 da clínica é .xls: o TI a salva
# como .xlsx antes, porque o OpenPyXL só lê o formato novo.
ARQUIVOS = {"p1": "p1_enderecos.xlsx", "p4": "p4_entradas.xlsx", "p3": "p3_eventos.xlsx"}
TAMANHO_MAXIMO = 20 * 1024 * 1024  # as três planilhas reais somam poucas centenas de kB
LINHAS_CABECALHO_P4 = 10  # a P4 tem um "2009" solto na linha 1 e o cabeçalho na 2


@dataclass(frozen=True, slots=True)
class Planilhas:
    p1: tuple[BlocoP1, ...]
    p4: tuple[LinhaP4, ...]
    p3: tuple[LinhaP3, ...]


def valor_da_celula(valor: Any) -> Valor:
    """Data como date; número como texto sem o '.0' do Excel; texto como está; vazio como None."""
    if valor is None:
        return None
    if isinstance(valor, datetime):
        return valor.date()
    if isinstance(valor, date):
        return valor
    if isinstance(valor, float) and valor.is_integer():
        return str(int(valor))
    texto = str(valor)
    return texto if texto.strip() else None


def _abrir(pasta: Path, chave: str) -> Any:
    caminho = pasta / ARQUIVOS[chave]
    if not caminho.is_file():
        raise RegraViolada("carga.planilha_ausente", {"planilha": chave})
    if caminho.stat().st_size > TAMANHO_MAXIMO:
        raise RegraViolada("carga.planilha_grande", {"planilha": chave})
    try:
        return load_workbook(caminho, read_only=True, data_only=True, keep_links=False)
    except OSError, ValueError, KeyError, zipfile.BadZipFile:
        raise RegraViolada("carga.planilha_ilegivel", {"planilha": chave}) from None


def _linhas(folha: Any) -> Iterator[tuple[int, tuple[Valor, ...]]]:
    for numero, linha in enumerate(folha.iter_rows(values_only=True), start=1):
        yield numero, tuple(valor_da_celula(v) for v in linha)


def blocos_p1(linhas: Iterator[tuple[int, tuple[Valor, ...]]]) -> tuple[BlocoP1, ...]:
    """Fichas separadas por linha inteiramente vazia; rótulo na coluna A, valor na B (perfilamento §2)."""
    blocos: list[BlocoP1] = []
    atual: list[CelulaP1] = []
    for numero, valores in linhas:
        a = valores[0] if valores else None
        b = valores[1] if len(valores) > 1 else None
        if a is None and b is None:
            if atual:
                blocos.append(BlocoP1(atual[0].linha, tuple(atual)))
                atual = []
            continue
        atual.append(CelulaP1(numero, str(a) if a is not None and not isinstance(a, date) else "", b))
    if atual:
        blocos.append(BlocoP1(atual[0].linha, tuple(atual)))
    return tuple(blocos)


def linhas_p4(linhas: Iterator[tuple[int, tuple[Valor, ...]]]) -> tuple[LinhaP4, ...]:
    """Tabela com o cabeçalho numa das primeiras linhas; as colunas são achadas pelo rótulo, não pela posição."""
    colunas: dict[int, str] | None = None
    lidas: list[LinhaP4] = []
    for numero, valores in linhas:
        if colunas is None:
            rotulos = {i: norm_rotulo(v) for i, v in enumerate(valores) if isinstance(v, str)}
            if "PRONT" in rotulos.values():
                colunas = {i: r for i, r in rotulos.items() if r in COLUNAS_P4}
            elif numero >= LINHAS_CABECALHO_P4:
                raise RegraViolada("carga.p4_cabecalho")
            continue
        if all(v is None for v in valores):
            continue
        lidas.append(LinhaP4(numero, {r: valores[i] if i < len(valores) else None for i, r in colunas.items()}))
    if colunas is None:
        raise RegraViolada("carga.p4_cabecalho")
    return tuple(lidas)


def linhas_p3(aba: str, linhas: Iterator[tuple[int, tuple[Valor, ...]]]) -> tuple[LinhaP3, ...]:
    """Blocos por ano (ND-56): o ano do cabeçalho vale para as linhas seguintes; sentinelas não são registro."""
    coluna = coluna_do_nome_p3(aba)
    ano: int | None = None
    lidas: list[LinhaP3] = []
    for numero, valores in linhas:
        tipo, dado = classificar_linha_p3(valores, coluna)
        if tipo == "ano" and isinstance(dado, int):
            ano = dado
        elif tipo == "registro" and isinstance(dado, str):
            texto = tuple(v.strftime("%d/%m/%Y") if isinstance(v, date) else (v or "") for v in valores)
            lidas.append(LinhaP3(aba, numero, ano, dado, texto))
    return tuple(lidas)


def ler(pasta: Path) -> Planilhas:
    p1 = _abrir(pasta, "p1")
    try:
        blocos = blocos_p1(_linhas(p1.worksheets[0]))
    finally:
        p1.close()
    p4 = _abrir(pasta, "p4")
    try:
        entradas = linhas_p4(_linhas(p4.worksheets[0]))
    finally:
        p4.close()
    p3 = _abrir(pasta, "p3")
    try:
        eventos = tuple(linha for folha in p3.worksheets for linha in linhas_p3(folha.title, _linhas(folha)))
    finally:
        p3.close()
    return Planilhas(blocos, entradas, eventos)
