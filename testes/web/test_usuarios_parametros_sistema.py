"""Telas de usuários, parâmetros e convênios no navegador: teclado e axe-core (RNF-406)."""

from __future__ import annotations

import pytest
from playwright.sync_api import Page, expect
from sqlalchemy import Engine, text

from testes.apoio.acesso import CriarUsuario
from testes.conftest import ZERAR_TRILHA
from testes.web.conftest import entrar_no_navegador, sem_violacao

pytestmark = pytest.mark.sistema


@pytest.mark.requisito("RNF-406", "RF-1002")
def test_ti_cria_usuario_pelo_navegador_sem_violacao(
    criar_usuario: CriarUsuario, endereco: str, page: Page, trilha_zerada: Engine
) -> None:
    criar_usuario("sisu_ti", perfil="ti")
    try:
        entrar_no_navegador(page, endereco, "sisu_ti")
        page.get_by_role("link", name="Usuários").click()
        expect(page.get_by_role("table", name="Usuários do sistema")).to_be_visible()
        sem_violacao(page)
        page.get_by_role("link", name="Novo usuário").click()
        sem_violacao(page)
        page.get_by_label("Nome").fill("Bruna Fictício")
        page.get_by_label("Login").fill("sisu_bruna")
        page.get_by_label("Perfil").select_option("enfermagem")
        page.get_by_role("button", name="Criar usuário").click()
        expect(page.get_by_text("Senha provisória de sisu_bruna")).to_be_visible()
        sem_violacao(page)
    finally:
        with trilha_zerada.begin() as c:
            for comando in ZERAR_TRILHA:
                c.execute(text(comando))
            c.execute(text("DELETE FROM usuario WHERE login = 'sisu_bruna'"))


@pytest.mark.requisito("RNF-406", "DD-48")
def test_administracao_altera_parametro_pelo_teclado(
    criar_usuario: CriarUsuario, endereco: str, page: Page, trilha_zerada: Engine
) -> None:
    criar_usuario("sisu_admin", perfil="administracao")
    try:
        entrar_no_navegador(page, endereco, "sisu_admin")
        page.get_by_role("link", name="Parâmetros").click()
        sem_violacao(page)
        campo = page.get_by_label("Prazo do rascunho de cadastro")
        campo.fill("4")
        campo.press("Enter")  # sem mouse
        expect(page.get_by_role("status")).to_contain_text("Prazo do rascunho de cadastro: valor alterado.")
        expect(page.get_by_label("Prazo do rascunho de cadastro")).to_have_value("4")
    finally:
        with trilha_zerada.begin() as c:
            for comando in ZERAR_TRILHA:
                c.execute(text(comando))
            c.execute(text("DELETE FROM parametro"))


@pytest.mark.requisito("RNF-406", "RF-1204")
def test_administracao_inclui_e_inativa_convenio_pelo_teclado(
    criar_usuario: CriarUsuario, endereco: str, page: Page, trilha_zerada: Engine
) -> None:
    criar_usuario("sisu_admin2", perfil="administracao")
    try:
        entrar_no_navegador(page, endereco, "sisu_admin2")
        page.get_by_role("link", name="Convênios").click()
        sem_violacao(page)
        campo = page.get_by_label("Nome do convênio", exact=True)
        campo.fill("Ipasgo")
        campo.press("Enter")
        expect(page.get_by_role("status")).to_contain_text("Convênio incluído.")
        page.get_by_role("button", name="Inativar Ipasgo").click()
        expect(page.get_by_role("status")).to_contain_text("Convênio inativado.")
        expect(page.get_by_role("button", name="Reativar Ipasgo")).to_be_visible()
        sem_violacao(page)
    finally:
        with trilha_zerada.begin() as c:
            for comando in ZERAR_TRILHA:
                c.execute(text(comando))
            c.execute(text("DELETE FROM convenio"))
