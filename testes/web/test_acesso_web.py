"""Entrada, sessão e saída pela web, com o banco de testes (DD-19, DD-84, DD-85)."""

from __future__ import annotations

import re

import pytest
from flask import Flask
from flask.testing import FlaskClient
from sqlalchemy import Engine
from werkzeug.test import TestResponse

from sar.composicao import compor
from sar.web import COOKIE_SESSAO, criar_app
from sar.web.configuracao import ConfigWeb, ServicosWeb
from testes.apoio.acesso import HASHER, SENHA, CriarUsuario

pytestmark = pytest.mark.integracao

ORIGEM = "https://sar.teste"


def montar(engine: Engine, **config: object) -> Flask:
    componentes = compor(engine, bytes(32), hasher=HASHER)
    return criar_app(ServicosWeb(componentes.autenticacao, componentes.sessoes), ConfigWeb(origem=ORIGEM, **config))  # type: ignore[arg-type]


def cliente(app: Flask) -> FlaskClient:
    return app.test_client()


def get(c: FlaskClient, caminho: str) -> TestResponse:
    return c.get(caminho, base_url=ORIGEM)


def post(c: FlaskClient, caminho: str, dados: dict[str, str], origem: str | None = ORIGEM) -> TestResponse:
    cabecalhos = {"Origin": origem} if origem else {}
    return c.post(caminho, data=dados, base_url=ORIGEM, headers=cabecalhos)


def entrar(c: FlaskClient, login: str, senha: str = SENHA) -> TestResponse:
    return post(c, "/entrar", {"login": login, "senha": senha})


@pytest.mark.requisito("RF-1002")
def test_sem_sessao_qualquer_tela_leva_a_entrada(engine_web: Engine) -> None:
    resposta = get(cliente(montar(engine_web)), "/")
    assert resposta.status_code == 302 and resposta.headers["Location"].endswith("/entrar")


@pytest.mark.requisito("DD-84")
@pytest.mark.parametrize("origem", [None, "https://outro.site", "http://sar.teste"])
def test_post_sem_a_origem_do_sar_e_recusado(
    criar_usuario: CriarUsuario, engine_web: Engine, origem: str | None
) -> None:
    criar_usuario("web_csrf")
    resposta = post(cliente(montar(engine_web)), "/entrar", {"login": "web_csrf", "senha": SENHA}, origem)
    assert resposta.status_code == 403
    assert COOKIE_SESSAO not in resposta.headers.get("Set-Cookie", "")


@pytest.mark.requisito("DD-19", "DD-05", "DD-84")
def test_entrada_grava_o_cookie_com_os_atributos_da_dd19(criar_usuario: CriarUsuario, engine_web: Engine) -> None:
    criar_usuario("web_cookie")
    resposta = entrar(cliente(montar(engine_web)), "web_cookie")
    assert resposta.status_code == 302 and resposta.headers["Location"].endswith("/")
    cookie = resposta.headers["Set-Cookie"]
    assert cookie.startswith(f"{COOKIE_SESSAO}=")
    for atributo in ("Secure", "HttpOnly", "SameSite=Strict", "Path=/"):
        assert atributo in cookie
    assert "Domain" not in cookie and "Expires" not in cookie and "Max-Age" not in cookie


@pytest.mark.requisito("RF-1002", "CT-ACE-04")
def test_senha_errada_mostra_a_mensagem_unica(criar_usuario: CriarUsuario, engine_web: Engine) -> None:
    criar_usuario("web_errada")
    c = cliente(montar(engine_web))
    for login in ("web_errada", "nao_existe"):
        corpo = post(c, "/entrar", {"login": login, "senha": "errada"}).get_data(as_text=True)
        assert 'role="alert">Login ou senha incorretos' in corpo


@pytest.mark.requisito("DD-83", "RF-1002")
def test_senha_provisoria_e_trocada_na_propria_entrada(criar_usuario: CriarUsuario, engine_web: Engine) -> None:
    criar_usuario("web_troca", trocar=True)
    c = cliente(montar(engine_web))
    corpo = entrar(c, "web_troca").get_data(as_text=True)
    assert 'name="nova_senha"' in corpo and "provisória" in corpo
    dados = {"login": "web_troca", "senha": SENHA, "nova_senha": "jabuticaba madura"}
    assert "não são iguais" in post(c, "/entrar", {**dados, "nova_senha_repetida": "outra"}).get_data(as_text=True)
    fraca = {**dados, "nova_senha": "12345678", "nova_senha_repetida": "12345678"}
    assert "fácil de adivinhar" in post(c, "/entrar", fraca).get_data(as_text=True)
    assert post(c, "/entrar", {**dados, "nova_senha_repetida": "jabuticaba madura"}).status_code == 302
    assert get(c, "/").status_code == 200


@pytest.mark.requisito("RNF-601", "CT-ACE-05", "DEC-63")
def test_nova_entrada_em_outra_estacao_derruba_a_primeira_com_aviso(
    criar_usuario: CriarUsuario, engine_web: Engine
) -> None:
    criar_usuario("web_duas")
    app = montar(engine_web)
    balcao, sala = cliente(app), cliente(app)
    entrar(balcao, "web_duas")
    entrar(sala, "web_duas")
    resposta = get(balcao, "/")
    assert resposta.status_code == 302 and resposta.headers["Location"].endswith("/entrar?motivo=novo_login")
    assert "outra estação" in get(balcao, "/entrar?motivo=novo_login").get_data(as_text=True)
    assert get(sala, "/").status_code == 200


@pytest.mark.requisito("RF-1002", "RNF-605")
def test_sair_encerra_a_sessao_e_apaga_o_cookie(criar_usuario: CriarUsuario, engine_web: Engine) -> None:
    criar_usuario("web_sair")
    c = cliente(montar(engine_web))
    entrar(c, "web_sair")
    token = c.get_cookie(COOKIE_SESSAO, domain="sar.teste")
    assert token is not None
    resposta = post(c, "/sair", {})
    assert resposta.headers["Location"].endswith("/entrar?motivo=saida")
    assert c.get_cookie(COOKIE_SESSAO, domain="sar.teste") is None
    outro = cliente(montar(engine_web))
    outro.set_cookie(COOKIE_SESSAO, token.value, domain="sar.teste", secure=True)
    assert get(outro, "/").headers["Location"].endswith("/entrar?motivo=saida")  # o token antigo não vale mais


@pytest.mark.requisito("AD-20", "RF-1004")
def test_menu_e_cabecalho_seguem_o_perfil(criar_usuario: CriarUsuario, engine_web: Engine) -> None:
    criar_usuario("web_menu", perfil="enfermagem")
    c = cliente(montar(engine_web))
    entrar(c, "web_menu")
    corpo = get(c, "/").get_data(as_text=True)
    assert 'data-sobre="perfil">Enfermagem<' in corpo
    assert re.search(r'href="/"[^>]*aria-current="page">Início', corpo)
    assert "Agir como" not in corpo  # o seletor do superusuário não aparece


@pytest.mark.requisito("DD-85")
def test_superusuario_troca_de_perfil_so_em_desenvolvimento(criar_usuario: CriarUsuario, engine_web: Engine) -> None:
    uid = criar_usuario("web_super", perfil="administracao")
    criar_usuario("web_comum")
    app = montar(engine_web, desenvolvimento=True, superusuarios=frozenset({uid}))
    c = cliente(app)
    entrar(c, "web_super")
    assert "Agir como" in get(c, "/").get_data(as_text=True)
    assert post(c, "/desenvolvimento/perfil", {"perfil": "ti"}).status_code == 302
    assert 'data-sobre="perfil">TI<' in get(c, "/").get_data(as_text=True)
    assert post(c, "/desenvolvimento/perfil", {"perfil": "sistema"}).status_code == 400

    comum = cliente(app)
    entrar(comum, "web_comum")
    assert post(comum, "/desenvolvimento/perfil", {"perfil": "ti"}).status_code == 404  # não é superusuário


@pytest.mark.requisito("DD-83")
def test_troca_da_propria_senha(criar_usuario: CriarUsuario, engine_web: Engine) -> None:
    criar_usuario("web_senha")
    c = cliente(montar(engine_web))
    entrar(c, "web_senha")
    errada = {"senha_atual": "não é", "nova_senha": "jabuticaba madura", "nova_senha_repetida": "jabuticaba madura"}
    assert "atual não confere" in post(c, "/senha", errada).get_data(as_text=True)
    certa = {**errada, "senha_atual": SENHA}
    assert "Senha trocada" in post(c, "/senha", certa).get_data(as_text=True)
