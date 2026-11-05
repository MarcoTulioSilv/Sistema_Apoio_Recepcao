"""Saídas do modelo tabular (DD-44, DD-45, RF-912): o PDF e o XLSX levam exatamente as colunas, os filtros e as marcas
da tabela (CT-REL-02), e no XLSX todo texto é texto, nunca fórmula (CT-REL-03)."""

from __future__ import annotations

import io
import re
import zipfile
from datetime import UTC, datetime

import pytest

from sar.modulo_05_emissao import exportacao
from sar.modulo_05_emissao.contrato import Coluna, Marca, Relatorio, Tabela
from testes.apoio.modelos import texto_do_pdf

PERIGOSOS = ['=HYPERLINK("http://198.51.100.7")', "+55 64 3600-0000", "-2+3", "@SOMA(A1:A2)", "=1+1"]


def tabela(nomes: list[str]) -> Tabela:
    return Tabela(
        relatorio=Relatorio.PREVIA,
        titulo=Relatorio.PREVIA.titulo,
        filtros=(("Competência", "10/2026"),),
        colunas=(Coluna("Paciente"), Coluna("Prontuário"), Coluna("Previstas", True), Coluna("Extras", True)),
        linhas=tuple((nome, f"P{i:03}", 13, i) for i, nome in enumerate(nomes)),
        marcas=(Marca("previa", "PRÉVIA — mês em aberto: os números mudam até o fechamento do mês."),
                Marca("mes_alterado", "Mês 09/2026 alterado após o fechamento em 13/10/2026. Motivo: correção")),
        gerado_em=datetime(2026, 10, 13, 13, 0, tzinfo=UTC),
        codigo_integridade="A1B2 C3D4 E5F6 0718 · nº 7 · 13/10/2026",
    )  # fmt: skip


def celulas(xlsx: bytes) -> tuple[list[str], str]:
    """Os textos das células (pela tabela de textos compartilhados) e o XML da planilha."""
    with zipfile.ZipFile(io.BytesIO(xlsx)) as pacote:
        compartilhados = pacote.read("xl/sharedStrings.xml").decode()
        planilha = pacote.read("xl/worksheets/sheet1.xml").decode()
    textos = [re.sub(r"<[^>]+>", "", t) for t in re.findall(r"<si>(.*?)</si>", compartilhados, flags=re.DOTALL)]
    return [t.replace("&amp;", "&").replace("&quot;", '"') for t in textos], planilha


@pytest.mark.requisito("RF-912", "DD-44", "DD-86", "DD-47", "CT-REL-02")
def test_pdf_e_xlsx_com_as_mesmas_colunas_filtros_e_marcas_da_tabela() -> None:
    dados = tabela(["Ana Exemplo", "Bruno Exemplo"])
    textos, _ = celulas(exportacao.para_xlsx(dados).conteudo)
    pdf = texto_do_pdf(exportacao.para_pdf(dados).conteudo)
    for esperado in (*(c.titulo for c in dados.colunas), *(m.texto for m in dados.marcas), "10/2026",
                     "Ana Exemplo", "Bruno Exemplo"):  # fmt: skip
        assert esperado in textos or any(esperado in t for t in textos), esperado
        assert " ".join(esperado.split()) in " ".join(pdf.split()), esperado
    assert any("A1B2 C3D4 E5F6 0718" in t for t in textos) and "A1B2 C3D4 E5F6 0718" in pdf
    cabecalhos = [t for t in textos if t in {c.titulo for c in dados.colunas}]
    assert cabecalhos == [c.titulo for c in dados.colunas]  # só as colunas do relatório, na ordem (RF-912)


@pytest.mark.requisito("DD-47")
def test_previa_leva_a_marca_em_cada_pagina_do_pdf() -> None:
    import pypdfium2 as pdfium

    pdf = exportacao.para_pdf(tabela([f"Paciente Fictício {i:03}" for i in range(120)])).conteudo
    documento = pdfium.PdfDocument(pdf)
    assert len(documento) > 1
    for pagina in range(len(documento)):
        assert "PRÉVIA" in documento[pagina].get_textpage().get_text_range()


@pytest.mark.requisito("DD-45", "CT-REL-03")
def test_texto_que_parece_formula_sai_como_texto_no_xlsx() -> None:
    textos, planilha = celulas(exportacao.para_xlsx(tabela(PERIGOSOS)).conteudo)
    assert "<f>" not in planilha  # nenhuma fórmula na planilha
    for perigoso in PERIGOSOS:
        assert perigoso in textos, perigoso
    numeros = re.findall(r'<c r="C\d+"(?: s="\d+")?><v>(\d+)</v></c>', planilha)  # sem t="s": número de fato
    assert numeros and set(numeros) == {"13"}  # número continua número
