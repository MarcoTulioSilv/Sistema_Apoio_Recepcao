"""PDF dos leiautes fixos (DD-105, DD-106) e, na etapa B, dos relatórios (DD-44): HTML do pacote convertido pelo
WeasyPrint, em memória. O buscador de recursos só aceita dados embutidos (`data:`); qualquer outro endereço para a
geração, em vez de ser buscado (DD-46)."""

from __future__ import annotations

import base64
from collections.abc import Mapping
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, StrictUndefined, select_autoescape
from weasyprint import HTML
from weasyprint.urls import URLFetcher

PASTA_LEIAUTES = Path(__file__).resolve().parent / "leiautes"


class _SoEmbutidos(URLFetcher):  # type: ignore[misc]
    def __init__(self) -> None:
        super().__init__(allowed_protocols={"data"}, allow_redirects=False, fail_on_errors=True)


_AMBIENTE = Environment(
    loader=FileSystemLoader(PASTA_LEIAUTES),
    autoescape=select_autoescape(["html"]),
    undefined=StrictUndefined,
    trim_blocks=True,
    lstrip_blocks=True,
)


def imagem_embutida(conteudo: bytes | None, tipo: str = "image/png") -> str | None:
    return f"data:{tipo};base64,{base64.b64encode(conteudo).decode()}" if conteudo else None


def html(leiaute: str, valores: Mapping[str, object]) -> str:
    """O HTML do leiaute, com escape automático de todo valor."""
    return _AMBIENTE.get_template(leiaute).render(**valores)


def para_pdf(conteudo_html: str) -> bytes:
    pdf: bytes = HTML(string=conteudo_html, url_fetcher=_SoEmbutidos()).write_pdf()  # sem destino: os bytes
    return pdf
