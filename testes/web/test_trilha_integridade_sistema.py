"""Autorizações, trilha e integridade no navegador: axe-core (RNF-406)."""

from __future__ import annotations

import pytest
from playwright.sync_api import Page, expect

from testes.apoio.acesso import CriarUsuario
from testes.web.conftest import entrar_no_navegador, sem_violacao

pytestmark = pytest.mark.sistema


@pytest.mark.requisito("RNF-406", "RNF-625", "RF-1011")
def test_telas_da_administracao_sem_violacao(criar_usuario: CriarUsuario, endereco: str, page: Page) -> None:
    criar_usuario("sist_admin", perfil="administracao")
    entrar_no_navegador(page, endereco, "sist_admin")
    for item, titulo in (
        ("Autorizações", "Autorizações"),
        ("Trilha de auditoria", "Trilha de auditoria"),
        ("Integridade", "Integridade"),
    ):
        page.get_by_role("link", name=item).click()
        expect(page.get_by_role("heading", name=titulo, level=1)).to_be_visible()
        sem_violacao(page)
    page.get_by_role("link", name="Trilha de auditoria").click()
    page.get_by_role("button", name="Consultar").click()
    expect(page.get_by_role("table")).to_be_visible()
    sem_violacao(page)
