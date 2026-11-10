"""Renderizadores do modelo tabular (DD-44, DD-45): o PDF pelo mesmo leiaute da tela, sem buscar nada fora (DD-46), e
o XLSX só com valores. As mesmas colunas, filtros e marcas nas duas saídas (RF-912), com o código de integridade
(DD-86). Tudo em memória, nada em disco."""

from __future__ import annotations

import io
from typing import Any

import xlsxwriter

from sar.modulo_05_emissao import pdf, regras
from sar.modulo_05_emissao.contrato import ArquivoRelatorio, Bloco, Composto, Tabela

PDF = "application/pdf"
XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
# DD-45: nenhum texto vira fórmula, número ou endereço, seja qual for o primeiro caractere (=, +, -, @).
OPCOES_XLSX = {"in_memory": True, "strings_to_formulas": False, "strings_to_numbers": False, "strings_to_urls": False}


Saida = Tabela | Composto


def documento(saida: Saida) -> Composto:
    """Uma tabela sai como um documento de uma tabela só; o composto (DD-109), com as tabelas em sequência."""
    if isinstance(saida, Composto):
        return saida
    return Composto(saida.titulo, saida.filtros, (saida,), saida.gerado_em, saida.codigo_integridade)


def _nome(saida: Saida, extensao: str) -> str:
    base = saida.relatorio.value if isinstance(saida, Tabela) else "cadastro"
    return f"{base}-{regras.hoje(saida.gerado_em).isoformat()}.{extensao}"


def gerado_em(saida: Saida) -> str:
    return saida.gerado_em.astimezone(regras.FUSO).strftime("%d/%m/%Y %H:%M")


def html(saida: Saida) -> str:
    return pdf.html("relatorio.html", {"doc": documento(saida), "gerado_em": gerado_em(saida)})


def para_pdf(saida: Saida) -> ArquivoRelatorio:
    return ArquivoRelatorio(pdf.para_pdf(html(saida)), _nome(saida, "pdf"), PDF)


def para_xlsx(saida: Saida) -> ArquivoRelatorio:
    doc = documento(saida)
    varias = len(doc.tabelas) > 1
    entrada = io.BytesIO()
    livro = xlsxwriter.Workbook(entrada, OPCOES_XLSX)
    livro.set_properties({"title": doc.titulo, "author": "", "company": "", "comments": ""})
    negrito = livro.add_format({"bold": True})
    cabecalho = livro.add_format({"bold": True, "bottom": 1})
    subtitulo = livro.add_format({"bold": True, "font_size": 12})
    folha = livro.add_worksheet("Relatório")
    linha = 0
    folha.write_string(linha, 0, doc.titulo, livro.add_format({"bold": True, "font_size": 13}))
    linha += 1
    for rotulo, valor in doc.filtros:
        folha.write_string(linha, 0, rotulo, negrito)
        folha.write_string(linha, 1, valor)
        linha += 1
    largura = max(len(t.colunas) for t in doc.tabelas)
    for coluna in range(largura):  # a coluna é numérica se for numérica em todas as tabelas que a têm
        numerica = all(t.colunas[coluna].numerica for t in doc.tabelas if coluna < len(t.colunas))
        folha.set_column(coluna, coluna, 14 if numerica else 32)

    def valores(linha: int, celulas: tuple[str | int, ...], formato: object = None) -> None:
        for coluna, celula in enumerate(celulas):
            if isinstance(celula, int):
                folha.write_number(linha, coluna, celula, formato)
            else:
                folha.write_string(linha, coluna, celula, formato)  # sempre texto, nunca fórmula (DD-45)

    for tabela in doc.tabelas:
        if varias:  # uma tabela embaixo da outra, cada uma com o seu título (DD-109)
            linha += 1
            folha.write_string(linha, 0, tabela.titulo, subtitulo)
            linha += 1
        for marca in tabela.marcas:
            folha.write_string(linha, 0, marca.texto, negrito)
            linha += 1
        if not varias:
            linha += 1
        linha = _tabela(folha, tabela, linha, valores, cabecalho, negrito, subtitulo, congelar=not varias)
    folha.write_string(linha, 0, f"Gerado em {gerado_em(doc)}")
    folha.write_string(linha + 1, 0, f"Código de integridade: {doc.codigo_integridade}")
    livro.close()
    return ArquivoRelatorio(entrada.getvalue(), _nome(saida, "xlsx"), XLSX)


def _tabela(folha: Any, tabela: Tabela, linha: int, valores: Any, cabecalho: object, negrito: object,
            subtitulo: object, congelar: bool) -> int:  # fmt: skip
    """Escreve a tabela a partir da linha e devolve a linha seguinte, já com uma em branco depois."""

    def cabeca(linha: int) -> None:
        for coluna, definicao in enumerate(tabela.colunas):
            folha.write_string(linha, coluna, definicao.titulo, cabecalho)

    if tabela.blocos:  # um bloco por vez: título, cabeçalho, linhas, total e uma linha em branco

        def bloco(linha: int, b: Bloco) -> int:
            folha.write_string(linha, 0, b.titulo, subtitulo)
            cabeca(linha + 1)
            linha += 1
            for celulas in b.linhas:
                linha += 1
                valores(linha, celulas)
            valores(linha + 1, ("Total", b.total), negrito)
            return linha + 3

        for b in (b for b in tabela.blocos if not b.separado):
            linha = bloco(linha, b)
        folha.write_string(linha, 0, tabela.total_geral, negrito)
        linha += 2
        for b in (b for b in tabela.blocos if b.separado):
            linha = bloco(linha, b)
        return linha
    cabeca(linha)
    if congelar:
        folha.freeze_panes(linha + 1, 0)
    for celulas in tabela.linhas:
        linha += 1
        valores(linha, celulas)
    return linha + 2
