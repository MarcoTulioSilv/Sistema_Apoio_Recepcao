"""Modelos .docx de teste, montados em memória a partir dos modelos iniciais (CT-EMI-01). Tudo inerte: as "macros"
são bytes sem código, os vínculos apontam para endereço reservado de documentação, e nada vai a disco."""

from __future__ import annotations

import io
import os
import zipfile
from collections.abc import Callable
from pathlib import Path

import pypdfium2 as pdfium
import pytest

from sar.modulo_05_emissao.contrato import Modelo
from sar.modulo_05_emissao.conversor import ConversorGotenberg
from sar.nucleo.erros import IndisponivelExterno

PASTA = Path(__file__).resolve().parents[2] / "sar" / "modulo_05_emissao" / "modelos_iniciais"
Partes = dict[str, bytes]
EXTERNO_INERTE = "http://198.51.100.7"  # endereço reservado para documentação (RFC 5737): nunca responde


def inicial(modelo: Modelo = Modelo.CATETER) -> bytes:
    return (PASTA / f"{modelo.value}.docx").read_bytes()


def partes(docx: bytes) -> Partes:
    with zipfile.ZipFile(io.BytesIO(docx)) as pacote:
        return {nome: pacote.read(nome) for nome in pacote.namelist()}


def montar(conteudo: Partes) -> bytes:
    saida = io.BytesIO()
    with zipfile.ZipFile(saida, "w", zipfile.ZIP_DEFLATED) as pacote:
        for nome, dados in conteudo.items():
            pacote.writestr(nome, dados)
    return saida.getvalue()


def alterado(mudar: Callable[[Partes], None], modelo: Modelo = Modelo.CATETER) -> bytes:
    conteudo = partes(inicial(modelo))
    mudar(conteudo)
    return montar(conteudo)


def no_texto(trecho: str, modelo: Modelo = Modelo.CATETER) -> bytes:
    """Troca a primeira variável {{ nome }} do modelo pelo trecho (que pode trazer Jinja hostil)."""

    def mudar(conteudo: Partes) -> None:
        documento = conteudo["word/document.xml"].decode()
        assert "{{ nome }}" in documento
        conteudo["word/document.xml"] = documento.replace("{{ nome }}", trecho, 1).encode()

    return alterado(mudar, modelo)


def conversor_no_ar() -> ConversorGotenberg:
    """O conversor do compose (DD-104); sem ele, o teste é pulado, salvo com SAR_EXIGIR_CONVERSOR=1 (CI)."""
    conversor = ConversorGotenberg(tempo=60)
    try:
        conversor.para_pdf(inicial())
    except IndisponivelExterno:
        if os.environ.get("SAR_EXIGIR_CONVERSOR") == "1":
            raise
        pytest.skip("conversor fora do ar (docker compose up -d conversor conversor-ponte); o CI roda este teste")
    return conversor


def texto_do_pdf(pdf: bytes) -> str:
    documento = pdfium.PdfDocument(pdf)
    return "\n".join(documento[i].get_textpage().get_text_range() for i in range(len(documento)))
