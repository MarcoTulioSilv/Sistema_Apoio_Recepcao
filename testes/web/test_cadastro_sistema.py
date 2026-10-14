"""Novo cadastro no navegador: htmx e o script da tela sob a CSP estrita (DD-09), teclado e axe-core (RNF-406)."""

from __future__ import annotations

import pytest
from playwright.sync_api import Page, expect
from sqlalchemy import Engine, text

from testes.apoio.acesso import CriarUsuario
from testes.apoio.fabrica import Fabrica
from testes.web.conftest import entrar_no_navegador, sem_violacao

pytestmark = pytest.mark.sistema


@pytest.mark.requisito("RNF-406", "RF-919", "RF-201", "QAS-03", "DD-09")
def test_cadastro_completo_pelo_navegador(
    criar_usuario: CriarUsuario, cadastro_zerado: dict[str, int], endereco: str, page: Page,
    engine_web: Engine, fabrica: Fabrica,
) -> None:  # fmt: skip
    erros: list[str] = []
    page.on("console", lambda m: erros.append(m.text) if m.type == "error" else None)
    page.on("pageerror", lambda e: erros.append(str(e)))
    criar_usuario("sistcad_rec")
    entrar_no_navegador(page, endereco, "sistcad_rec")
    page.get_by_role("link", name="Novo cadastro").click()
    expect(page.get_by_role("heading", name="Novo cadastro", level=1)).to_be_visible()
    sem_violacao(page)

    salvar = page.get_by_role("button", name="Salvar paciente")
    expect(salvar).to_be_disabled()  # mínimo da P-03 contado pelo script da tela
    page.get_by_label("Nome completo").fill(fabrica.nome())
    page.get_by_label("Nome completo").press("Tab")  # "change": o htmx salva o rascunho
    expect(page.locator("#rascunho-estado")).to_contain_text("Rascunho salvo automaticamente às")

    page.get_by_label("CPF").fill("111.111.111-11")
    page.get_by_label("CPF").press("Tab")
    expect(page.locator("#cpf-erro")).to_contain_text("CPF inválido")  # conferência imediata pelo servidor
    page.get_by_label("CPF").fill("")
    page.get_by_label("CPF").press("Tab")
    expect(page.locator("#cpf-erro")).to_have_text("")

    page.get_by_label("CEP").fill("75800-000")
    page.get_by_label("CEP").press("Tab")  # o provedor dos testes está fora do ar
    expect(page.get_by_text("Consulta de CEP fora do ar")).to_be_visible()

    page.get_by_role("button", name="Adicionar telefone", exact=True).click()
    expect(page.locator('input[name="tel-1-ddd"]')).to_be_focused()  # linha nova, com o foco nela
    page.locator('input[name="tel-0-ddd"]').fill("64")
    page.locator('input[name="tel-0-numero"]').fill("999990001")
    page.locator('input[name="tel-1-ddd"]').fill("64")
    page.locator('input[name="tel-1-numero"]').fill("36310002")
    page.locator('select[name="tel-1-tipo"]').select_option("fixo")
    page.get_by_role("button", name="Adicionar contato").click()
    page.locator('input[name="contato-1-nome"]').fill(fabrica.nome())
    sem_violacao(page)

    page.get_by_label("Prontuário").fill(fabrica.prontuario())
    page.get_by_label("Início do tratamento").fill("2026-10-01")
    expect(salvar).to_be_enabled()
    salvar.click()
    expect(page.get_by_role("status").filter(has_text="Paciente cadastrado")).to_be_visible()
    sem_violacao(page)

    with engine_web.connect() as c:
        assert c.execute(text("SELECT COUNT(*) FROM telefone")).scalar_one() == 2
        assert c.execute(text("SELECT COUNT(*) FROM contato")).scalar_one() == 1
        assert c.execute(text("SELECT cep_verificado FROM paciente")).scalar_one() == 0  # CT-CAD-04
        assert c.execute(text("SELECT COUNT(*) FROM rascunho_cadastro")).scalar_one() == 0
    assert erros == []  # nenhum bloqueio da CSP nem erro de script
