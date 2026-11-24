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
    ROTULOS,
    BlocoP1,
    CelulaP1,
    LinhaP3,
    LinhaP4,
    Valor,
    campo_do_rotulo,
    classificar_linha_p3,
    coluna_do_nome_p3,
    comeca_ficha,
    norm_rotulo,
)
from sar.nucleo.erros import RegraViolada

# Os nomes que o TI dá às planilhas na pasta da carga (docs/comandos.md). A P4 da clínica é .xls: o TI a salva
# como .xlsx antes, porque o OpenPyXL só lê o formato novo.
ARQUIVOS = {"p1": "p1_enderecos.xlsx", "p4": "p4_entradas.xlsx", "p3": "p3_eventos.xlsx"}
TAMANHO_MAXIMO = 20 * 1024 * 1024  # as três planilhas reais somam poucas centenas de kB
LINHAS_CABECALHO_P4 = 10  # a P4 tem um "2009" solto na linha 1 e o cabeçalho na 2
MINIMO_ROTULOS = 3  # uma ficha tem 9; uma tabela com os mesmos nomes no cabeçalho tem no máximo 1 na coluna A


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


ESPACO_STRICT = (
    b"purl.oclc.org/ooxml"  # o da "Planilha Strict Open XML"; o formato comum usa schemas.openxmlformats.org
)


def formato_strict(caminho: Path) -> bool:
    """Visto no uso (17/11/2026): a P4 salva pelo Excel como "Planilha Strict Open XML" tem extensão .xlsx, mas o
    OpenPyXL não entende esse formato e descarta todas as abas. Olha só o cabeçalho do índice das abas, nunca célula."""
    with zipfile.ZipFile(caminho) as pacote:
        try:
            with pacote.open("xl/workbook.xml") as indice:
                return ESPACO_STRICT in indice.read(4096)
        except KeyError:
            return False


def _abrir(pasta: Path, chave: str) -> Any:
    caminho = pasta / ARQUIVOS[chave]
    if not caminho.is_file():
        raise RegraViolada("carga.planilha_ausente", {"planilha": chave})
    if caminho.stat().st_size > TAMANHO_MAXIMO:
        raise RegraViolada("carga.planilha_grande", {"planilha": chave})
    try:
        if formato_strict(caminho):
            raise RegraViolada("carga.planilha_strict", {"planilha": chave})
        livro = load_workbook(caminho, read_only=True, data_only=True, keep_links=False)
    except OSError, ValueError, KeyError, zipfile.BadZipFile:
        raise RegraViolada("carga.planilha_ilegivel", {"planilha": chave}) from None
    if not livro.worksheets:
        # Visto no uso: um .xls convertido fora do Excel e do LibreOffice, com a definição da aba inválida; o OpenPyXL
        # descarta a aba com um aviso e o livro abre vazio.
        livro.close()
        raise RegraViolada("carga.planilha_sem_aba", {"planilha": chave})
    return livro


def _linhas(folha: Any) -> Iterator[tuple[int, tuple[Valor, ...]]]:
    for numero, linha in enumerate(folha.iter_rows(values_only=True), start=1):
        yield numero, tuple(valor_da_celula(v) for v in linha)


def celula_preta(celula: Any) -> bool:
    """Preenchimento sólido preto: a cor direta, "Preto, Texto 1" do tema ou o preto da paleta antiga."""
    preenchimento = getattr(celula, "fill", None)
    if preenchimento is None or preenchimento.fill_type != "solid":
        return False
    cor = preenchimento.fgColor
    if cor.type == "rgb":
        return isinstance(cor.rgb, str) and cor.rgb[-6:].upper() == "000000"
    if cor.type == "theme":
        return cor.theme == 1 and not cor.tint
    return bool(cor.type == "indexed" and cor.indexed == 8)


LinhaP1 = tuple[int, tuple[Valor, ...] | None]  # None: a faixa preta entre as fichas


def linhas_p1(folha: Any) -> Iterator[LinhaP1]:
    """As linhas da P1, com a faixa preta entre as fichas lida como separador mesmo que tenha texto (escondido, preto
    no preto): a P1 real separa as fichas de 9 linhas por uma linha pintada de preto (visto no uso, 18/11/2026)."""
    for numero, linha in enumerate(folha.iter_rows(), start=1):
        if any(celula_preta(c) for c in linha[:2]):
            yield numero, None
        else:
            yield numero, tuple(valor_da_celula(getattr(c, "value", None)) for c in linha)


def blocos_p1(linhas: Iterator[LinhaP1]) -> tuple[BlocoP1, ...]:
    """Rótulo na coluna A, valor na B (perfilamento §2). Uma ficha começa na linha de rótulo PACIENTE que vem depois da
    faixa preta (DD-114, visto no uso em 18/11/2026); linha vazia não separa nada. A planilha é feita à mão, copiando
    a ficha de cima: um PACIENTE no meio da ficha (na linha da cidade) não começa outra, e a faixa seguida de outra
    coisa também não. O título no alto da aba fica num bloco só dele, que não tem rótulo de ficha (SEM_FICHA)."""
    blocos: list[BlocoP1] = []
    atual: list[CelulaP1] = []
    depois_da_faixa = False
    for numero, valores in linhas:
        if valores is None:
            depois_da_faixa = True
            continue
        a = valores[0] if valores else None
        b = valores[1] if len(valores) > 1 else None
        if a is None and b is None:
            continue
        sem_ficha = not any(campo_do_rotulo(c.rotulo) for c in atual)
        if atual and comeca_ficha(a) and (depois_da_faixa or sem_ficha):
            blocos.append(BlocoP1(atual[0].linha, tuple(atual)))
            atual = []
        depois_da_faixa = False
        atual.append(CelulaP1(numero, str(a) if a is not None and not isinstance(a, date) else "", b))
    if atual:
        blocos.append(BlocoP1(atual[0].linha, tuple(atual)))
    return tuple(blocos)


def aba_de_fichas(livro: Any) -> list[LinhaP1]:
    """A aba da P1 que a carga lê (DD-114): a única aba visível com fichas, isto é, com rótulos da ficha na coluna A.
    Visto no uso (17/11/2026): a P1 real tem, além da aba original, uma tentativa de tabela (um dado por coluna) e duas
    abas ocultas. Aba oculta não conta: é o que a recepção não vê."""
    escolhidas: list[list[LinhaP1]] = []
    for folha in livro.worksheets:
        if folha.sheet_state != "visible":
            continue
        linhas = list(linhas_p1(folha))
        rotulos = sum(1 for _, valores in linhas if valores and norm_rotulo(valores[0]) in ROTULOS)
        if rotulos >= MINIMO_ROTULOS:
            escolhidas.append(linhas)
    if not escolhidas:
        raise RegraViolada("carga.p1_sem_fichas", {"planilha": "p1"})
    if len(escolhidas) > 1:
        raise RegraViolada("carga.p1_varias_abas", {"planilha": "p1"})
    return escolhidas[0]


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
                raise RegraViolada("carga.p4_cabecalho", {"planilha": "p4"})
            continue
        if all(v is None for v in valores):
            continue
        lidas.append(LinhaP4(numero, {r: valores[i] if i < len(valores) else None for i, r in colunas.items()}))
    if colunas is None:
        raise RegraViolada("carga.p4_cabecalho", {"planilha": "p4"})
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
        blocos = blocos_p1(iter(aba_de_fichas(p1)))
    finally:
        p1.close()
    p4 = _abrir(pasta, "p4")
    try:
        visiveis = [folha for folha in p4.worksheets if folha.sheet_state == "visible"]
        entradas = linhas_p4(_linhas((visiveis or p4.worksheets)[0]))
    finally:
        p4.close()
    p3 = _abrir(pasta, "p3")
    try:
        eventos = tuple(linha for folha in p3.worksheets for linha in linhas_p3(folha.title, _linhas(folha)))
    finally:
        p3.close()
    return Planilhas(blocos, entradas, eventos)
