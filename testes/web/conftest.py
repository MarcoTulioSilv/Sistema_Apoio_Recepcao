"""Servidor e navegador dos testes de sistema da web (Playwright), com o banco de testes."""

from __future__ import annotations

import threading
from collections.abc import Iterable, Iterator
from typing import TYPE_CHECKING

import pytest
from axe_playwright_python.sync_playwright import Axe
from playwright.sync_api import Browser, Page, sync_playwright
from sqlalchemy import Engine
from werkzeug.serving import WSGIRequestHandler, make_server

from sar.nucleo.portas import Relogio

if TYPE_CHECKING:
    from _typeshed.wsgi import StartResponse, WSGIApplication, WSGIEnvironment
from sar.web import criar_app
from sar.web.configuracao import ConfigWeb
from testes.apoio.acesso import SENHA
from testes.apoio.cadastro import ProvedorCepFalso
from testes.apoio.web import servicos_web

PORTA = 18765


class SemLogDeAcesso(WSGIRequestHandler):
    """Em produção o acesso é registrado pelo Caddy, sem a query (DD-81); o servidor de teste não registra."""

    def log_request(self, code: int | str = "-", size: int | str = "-") -> None:
        pass


def em_memoria(app: WSGIApplication) -> WSGIApplication:
    """Cada resposta lida inteira e o arquivo fechado antes de ir para a rede. O servidor de desenvolvimento do
    Werkzeug não fecha o arquivo estático quando o navegador derruba a conexão no meio (navegou antes de terminar), e
    o ResourceWarning derrubava testes ao acaso. Só no servidor de teste: os estáticos são pequenos."""

    def wsgi(environ: WSGIEnvironment, start_response: StartResponse) -> Iterable[bytes]:
        corpo = app(environ, start_response)
        try:
            return [b"".join(corpo)]
        finally:
            fechar = getattr(corpo, "close", None)
            if fechar is not None:
                fechar()

    return wsgi


@pytest.fixture
def provedor_cep() -> ProvedorCepFalso:
    """O CEP do servidor de teste: começa fora do ar (nenhum teste acessa a internet); o teste pode ligá-lo."""
    return ProvedorCepFalso()


@pytest.fixture
def relogio_do_servidor() -> Relogio | None:
    """O relógio do servidor de teste: o do sistema, salvo quando o teste fixa a hora (a tela inicial depende dela)."""
    return None


@pytest.fixture
def endereco(engine_web: Engine, provedor_cep: ProvedorCepFalso, relogio_do_servidor: Relogio | None) -> Iterator[str]:
    origem = f"http://127.0.0.1:{PORTA}"  # HTTP só em desenvolvimento (DD-80); o cookie é Secure mesmo assim
    servicos = servicos_web(engine_web, provedor_cep, relogio_do_servidor)
    app = criar_app(servicos, ConfigWeb(origem=origem, desenvolvimento=True))
    servidor = make_server("127.0.0.1", PORTA, em_memoria(app), request_handler=SemLogDeAcesso)
    linha = threading.Thread(target=servidor.serve_forever, daemon=True)
    linha.start()
    yield origem
    servidor.shutdown()


@pytest.fixture(scope="module")
def navegador() -> Iterator[Browser]:
    # Câmera falsa (padrão de teste) com a permissão concedida sem diálogo: só age quando a página pede a câmera.
    with sync_playwright() as p:
        navegador = p.chromium.launch(args=["--use-fake-device-for-media-stream", "--use-fake-ui-for-media-stream"])
        yield navegador
        navegador.close()


@pytest.fixture
def page(navegador: Browser) -> Iterator[Page]:
    contexto = navegador.new_context()
    yield contexto.new_page()
    contexto.close()


def sem_violacao(page: Page) -> None:
    resultado = Axe().run(page)
    assert resultado.violations_count == 0, resultado.generate_report()


def entrar_no_navegador(page: Page, endereco: str, login: str, senha: str = SENHA) -> None:
    page.goto(f"{endereco}/entrar")
    page.get_by_label("Login").fill(login)
    page.get_by_label("Senha").fill(senha)
    page.get_by_role("button", name="Entrar").click()
