"""Carga inicial no navegador (DDS §14.3): do menu ao aceite, pelo teclado onde a decisão é tomada, com axe-core em
cada tela (RNF-406) e nenhum erro de script (DD-09). Planilhas sintéticas (PT §5.3), efetivadas como o TI faria."""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from playwright.sync_api import Page, expect
from sqlalchemy import Engine

from sar.modulo_10_carga.contrato import CAMPOS_CONFERIDOS
from testes.apoio import planilhas
from testes.apoio.acesso import CriarUsuario
from testes.apoio.carga import ti
from testes.apoio.web import servicos_web
from testes.web.conftest import entrar_no_navegador, sem_violacao
from testes.web.test_pendencias_sistema import vigiar_erros

pytestmark = pytest.mark.sistema


@pytest.mark.requisito("RF-1106", "P-29", "DD-69", "DD-114", "RNF-406")
def test_da_excecao_ao_aceite(
    carga: dict[str, int],
    criar_usuario: CriarUsuario,
    engine_web: Engine,
    endereco: str,
    page: Page,
    sinteticas: tuple[planilhas.Sinteticas, Path],
) -> None:
    erros = vigiar_erros(page)
    gerado, pasta = sinteticas
    servicos_web(engine_web).carga.efetivar(ti(carga), pasta)
    criar_usuario("sistcarga_adm", perfil="administracao")
    entrar_no_navegador(page, endereco, "sistcarga_adm")

    page.get_by_role("navigation", name="Navegação principal").get_by_role("link", name="Carga inicial").click()
    expect(page.get_by_role("heading", name="Exceções: fichas que não entraram")).to_be_visible()
    sem_violacao(page)

    # Cada exceção, decidida pelo teclado: a escolha nas setas, o motivo e o Enter.
    while (pendente := page.locator('[data-estado="a"]').first).count():
        pendente.get_by_role("radio", name="Descartar").focus()
        page.keyboard.press("Space")
        pendente.get_by_label(re.compile("^Motivo")).fill("conferido com a recepção")
        page.keyboard.press("Enter")
        expect(page.get_by_role("status")).to_have_text("Decisão registrada.")
    expect(page.locator('[data-estado="d"]')).to_have_count(gerado.esperados()["excecoes"])

    page.get_by_role("link", name="Conferência amostral").click()
    expect(page.get_by_role("heading", name="15 pacientes sorteados")).to_be_visible()
    sem_violacao(page)
    for _ in range(15):
        page.get_by_role("link", name=re.compile("^Conferir")).first.click()
        expect(page.get_by_role("heading", name="Na planilha")).to_be_visible()
        for _, rotulo in CAMPOS_CONFERIDOS:
            page.get_by_role("group", name=rotulo, exact=True).get_by_text("Confere", exact=True).click()
        page.get_by_role("button", name="Registrar a conferência").click()
        expect(page.get_by_text("13 de 13 campos registrados")).to_be_visible()
        page.get_by_role("link", name="Voltar à amostra").click()
    sem_violacao(page)

    importados = gerado.esperados()["importados"]
    page.get_by_label(re.compile("^Pacientes em tratamento hoje")).fill(str(importados - 1))
    page.get_by_role("button", name="Aceitar a carga").click()
    expect(page.get_by_role("alert")).to_contain_text(f"diferente da carga ({importados})")
    sem_violacao(page)
    page.get_by_label("A diferença está explicada").check()
    page.get_by_role("button", name="Aceitar a carga").click()
    expect(page.get_by_role("status")).to_have_text("Carga aceita. A carga inicial está encerrada.")
    expect(
        page.get_by_role("navigation", name="Navegação principal").get_by_role("link", name="Carga inicial")
    ).to_have_count(0)
    # O 422 é a resposta prevista do aceite que pediu a confirmação da diferença; erro de script não pode haver.
    assert not [e for e in erros if "status of 422" not in e], erros
