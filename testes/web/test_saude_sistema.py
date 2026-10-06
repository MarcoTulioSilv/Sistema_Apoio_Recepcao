"""Página de saúde no navegador: carrega CSS e fonte locais sob a CSP e passa no axe-core."""

from __future__ import annotations

import threading
from collections.abc import Iterator

import pytest
from axe_playwright_python.sync_playwright import Axe
from playwright.sync_api import Browser, Page, expect, sync_playwright
from werkzeug.serving import WSGIRequestHandler, make_server

from sar.web import criar_app

pytestmark = pytest.mark.sistema


@pytest.fixture(scope="module")
def navegador() -> Iterator[Browser]:
    with sync_playwright() as p:
        navegador = p.chromium.launch()
        yield navegador
        navegador.close()


@pytest.fixture
def page(navegador: Browser) -> Iterator[Page]:
    contexto = navegador.new_context()
    yield contexto.new_page()
    contexto.close()


class SemLogDeAcesso(WSGIRequestHandler):
    """Em produção o acesso é registrado pelo Caddy, sem a query (DD-81); o servidor de teste não registra."""

    def log_request(self, code: int | str = "-", size: int | str = "-") -> None:
        pass


@pytest.fixture(scope="module")
def endereco() -> Iterator[str]:
    servidor = make_server("127.0.0.1", 0, criar_app(), request_handler=SemLogDeAcesso)
    linha = threading.Thread(target=servidor.serve_forever, daemon=True)
    linha.start()
    yield f"http://127.0.0.1:{servidor.server_port}"
    servidor.shutdown()


@pytest.mark.requisito("DD-09", "AD-05")
def test_saude_no_navegador_sem_violacao(page: Page, endereco: str) -> None:
    problemas: list[str] = []
    page.on("console", lambda m: problemas.append(m.text) if m.type == "error" else None)
    page.on("response", lambda r: problemas.append(f"{r.status} {r.url}") if r.status >= 400 else None)

    page.goto(f"{endereco}/saude")

    expect(page.get_by_role("heading", name="Sistema de Apoio à Recepção")).to_be_visible()
    fonte = page.evaluate("getComputedStyle(document.body).fontFamily")
    assert "Atkinson Hyperlegible" in fonte  # o CSS gerado pelo Tailwind foi servido e aplicado
    resultado = Axe().run(page)
    assert resultado.violations_count == 0, resultado.generate_report()
    assert problemas == []
