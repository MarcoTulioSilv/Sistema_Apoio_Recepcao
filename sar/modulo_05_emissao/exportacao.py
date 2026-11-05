"""Renderizadores do modelo tabular (DD-44, DD-45): o PDF pelo mesmo leiaute da tela, sem buscar nada fora (DD-46), e
o XLSX só com valores. As mesmas colunas, filtros e marcas nas duas saídas (RF-912), com o código de integridade
(DD-86). Tudo em memória, nada em disco."""

from __future__ import annotations

import io

import xlsxwriter

from sar.modulo_05_emissao import pdf, regras
from sar.modulo_05_emissao.contrato import ArquivoRelatorio, Tabela

PDF = "application/pdf"
XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
# DD-45: nenhum texto vira fórmula, número ou endereço, seja qual for o primeiro caractere (=, +, -, @).
OPCOES_XLSX = {"in_memory": True, "strings_to_formulas": False, "strings_to_numbers": False, "strings_to_urls": False}


def _nome(tabela: Tabela, extensao: str) -> str:
    return f"{tabela.relatorio.value}-{regras.hoje(tabela.gerado_em).isoformat()}.{extensao}"


def gerado_em(tabela: Tabela) -> str:
    return tabela.gerado_em.astimezone(regras.FUSO).strftime("%d/%m/%Y %H:%M")


def html(tabela: Tabela) -> str:
    return pdf.html("relatorio.html", {"tabela": tabela, "gerado_em": gerado_em(tabela)})


def para_pdf(tabela: Tabela) -> ArquivoRelatorio:
    return ArquivoRelatorio(pdf.para_pdf(html(tabela)), _nome(tabela, "pdf"), PDF)


def para_xlsx(tabela: Tabela) -> ArquivoRelatorio:
    saida = io.BytesIO()
    livro = xlsxwriter.Workbook(saida, OPCOES_XLSX)
    livro.set_properties({"title": tabela.titulo, "author": "", "company": "", "comments": ""})
    negrito = livro.add_format({"bold": True})
    cabecalho = livro.add_format({"bold": True, "bottom": 1})
    folha = livro.add_worksheet("Relatório")
    linha = 0
    folha.write_string(linha, 0, tabela.titulo, livro.add_format({"bold": True, "font_size": 13}))
    linha += 1
    for rotulo, valor in tabela.filtros:
        folha.write_string(linha, 0, rotulo, negrito)
        folha.write_string(linha, 1, valor)
        linha += 1
    for marca in tabela.marcas:
        folha.write_string(linha, 0, marca.texto, negrito)
        linha += 1
    linha += 1
    for coluna, definicao in enumerate(tabela.colunas):
        folha.write_string(linha, coluna, definicao.titulo, cabecalho)
        folha.set_column(coluna, coluna, 14 if definicao.numerica else 32)
    folha.freeze_panes(linha + 1, 0)
    for valores in tabela.linhas:
        linha += 1
        for coluna, celula in enumerate(valores):
            if isinstance(celula, int):
                folha.write_number(linha, coluna, celula)
            else:
                folha.write_string(linha, coluna, celula)  # sempre texto, nunca fórmula (DD-45)
    linha += 2
    folha.write_string(linha, 0, f"Gerado em {gerado_em(tabela)}")
    folha.write_string(linha + 1, 0, f"Código de integridade: {tabela.codigo_integridade}")
    livro.close()
    return ArquivoRelatorio(saida.getvalue(), _nome(tabela, "xlsx"), XLSX)
