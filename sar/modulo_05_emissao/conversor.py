"""Cliente do conversor .docx → PDF (DD-42, DD-104): o Gotenberg com o LibreOffice, numa rede interna sem saída.

O .docx vai e o PDF volta em memória, com tempo máximo; nada fica em disco no servidor. A única chamada HTTP fora do
cliente de CEP, e só para dentro da rede do SAR (o contrato `internet` do import-linter registra a exceção).
"""

from __future__ import annotations

import os
from typing import Protocol

import httpx

from sar.nucleo.erros import IndisponivelExterno

ENDERECO_PADRAO = "http://127.0.0.1:3000"  # a ponte do compose (DD-104)
ROTA = "/forms/libreoffice/convert"
TEMPO_MAXIMO = 30.0
PDF_MAXIMO = 30 * 1024 * 1024


class ConversorDocumentos(Protocol):
    def para_pdf(self, docx: bytes) -> bytes:
        """O PDF do .docx; IndisponivelExterno se o conversor não responder ou responder fora do esperado."""
        ...


class ConversorGotenberg:
    def __init__(self, endereco: str | None = None, tempo: float = TEMPO_MAXIMO) -> None:
        self._endereco = (endereco or os.environ.get("SAR_CONVERSOR") or ENDERECO_PADRAO).rstrip("/")
        self._tempo = tempo

    def para_pdf(self, docx: bytes) -> bytes:
        arquivo = ("documento.docx", docx, "application/vnd.openxmlformats-officedocument.wordprocessingml.document")
        try:
            with httpx.Client(timeout=self._tempo, follow_redirects=False, trust_env=False) as cliente:
                resposta = cliente.post(self._endereco + ROTA, files={"files": arquivo})
        except httpx.HTTPError:
            raise IndisponivelExterno("conversor") from None
        conteudo = resposta.content
        if resposta.status_code != 200 or not conteudo.startswith(b"%PDF-") or len(conteudo) > PDF_MAXIMO:
            raise IndisponivelExterno("conversor")
        return conteudo
