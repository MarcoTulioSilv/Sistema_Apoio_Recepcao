"""Entrada e saída no navegador (Playwright), com o banco de testes: cookie de sessão, teclado e axe-core."""

from __future__ import annotations

import pytest
from playwright.sync_api import Page, expect

from sar.web import COOKIE_SESSAO
from testes.apoio.acesso import SENHA, CriarUsuario
from testes.web.conftest import sem_violacao

pytestmark = pytest.mark.sistema  # usa o banco de testes, mas roda na etapa do Playwright


@pytest.mark.requisito("RF-1002", "DD-19", "RNF-406")
def test_entrar_pelo_teclado_e_sair(criar_usuario: CriarUsuario, endereco: str, page: Page) -> None:
    criar_usuario("sis_recepcao")
    page.goto(f"{endereco}/")
    expect(page).to_have_url(f"{endereco}/entrar")
    sem_violacao(page)

    page.get_by_label("Login").fill("sis_recepcao")
    page.get_by_label("Senha").fill(SENHA)
    page.keyboard.press("Enter")  # sem mouse
    expect(page).to_have_url(f"{endereco}/")
    expect(page.get_by_role("heading", name="Início")).to_be_visible()
    cookie = next(c for c in page.context.cookies() if c["name"] == COOKIE_SESSAO)
    assert cookie["secure"] and cookie["httpOnly"] and cookie["sameSite"] == "Strict"
    sem_violacao(page)

    page.get_by_role("button", name="Sair").click()
    expect(page).to_have_url(f"{endereco}/entrar?motivo=saida")
    expect(page.get_by_role("status")).to_contain_text("Você saiu do sistema")


@pytest.mark.requisito("RF-1002", "CT-ACE-04", "RNF-406")
def test_entrada_recusada_mostra_o_alerta_acessivel(criar_usuario: CriarUsuario, endereco: str, page: Page) -> None:
    criar_usuario("sis_errada")
    page.goto(f"{endereco}/entrar")
    page.get_by_label("Login").fill("sis_errada")
    page.get_by_label("Senha").fill("senha errada")
    page.get_by_role("button", name="Entrar").click()
    expect(page.get_by_role("alert")).to_have_text("Login ou senha incorretos. Confira e tente de novo.")
    expect(page.get_by_label("Senha")).to_be_focused()  # o login fica preenchido; a senha recebe o foco
    sem_violacao(page)


@pytest.mark.requisito("DD-83", "RNF-406")
def test_troca_da_senha_provisoria_no_navegador(criar_usuario: CriarUsuario, endereco: str, page: Page) -> None:
    criar_usuario("sis_provisoria", trocar=True)
    page.goto(f"{endereco}/entrar")
    page.get_by_label("Login").fill("sis_provisoria")
    page.get_by_label("Senha").fill(SENHA)
    page.get_by_role("button", name="Entrar").click()
    expect(page.get_by_role("status")).to_contain_text("provisória")
    sem_violacao(page)
    page.get_by_label("Senha provisória").fill(SENHA)
    page.get_by_label("Senha nova", exact=True).fill("jabuticaba madura")
    page.get_by_label("Repita a senha nova").fill("jabuticaba madura")
    page.get_by_role("button", name="Trocar a senha e entrar").click()
    expect(page.get_by_role("heading", name="Início")).to_be_visible()
