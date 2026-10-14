"""Autorizações, trilha e integridade no navegador: axe-core (RNF-406)."""

from __future__ import annotations

import re

import pytest
from playwright.sync_api import Page, expect
from sqlalchemy import Engine

from testes.apoio.acesso import CriarUsuario
from testes.apoio.cadastro import INICIO, dados_completos, montar, pessoa
from testes.apoio.fabrica import Fabrica
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


@pytest.mark.requisito("RNF-406", "RF-1008", "DD-09")
def test_decisao_com_seletor_e_dialogo_de_confirmacao(
    criar_usuario: CriarUsuario, cadastro_zerado: dict[str, int], endereco: str, page: Page, engine_web: Engine,
    fabrica: Fabrica,
) -> None:  # fmt: skip
    cadastro = montar(engine_web)
    recepcao = pessoa(cadastro_zerado)
    pid = cadastro.pacientes.criar(recepcao, dados_completos(fabrica), INICIO)
    cadastro.anulacao.solicitar(recepcao, pid, "Cadastro duplicado")
    erros: list[str] = []
    page.on("console", lambda m: erros.append(m.text) if m.type == "error" else None)
    criar_usuario("sist_adm_dec", perfil="administracao")
    entrar_no_navegador(page, endereco, "sist_adm_dec")
    page.get_by_role("link", name="Autorizações").click()
    page.get_by_role("link", name=re.compile(r"^Analisar")).click()
    expect(page.get_by_text("Cadastro duplicado")).to_be_visible()
    dialogo = page.get_by_role("dialog")
    page.get_by_role("button", name="Confirmar decisão").click()  # sem escolha: nada abre
    expect(page.get_by_text("Escolha aprovar ou negar antes de confirmar.")).to_be_visible()
    expect(dialogo).to_be_hidden()
    sem_violacao(page)

    page.get_by_text("Negar", exact=True).click()
    page.get_by_role("button", name="Confirmar decisão").click()
    expect(dialogo).to_be_visible()
    expect(dialogo.get_by_role("heading")).to_have_text("Negar este pedido?")
    expect(dialogo.get_by_role("button", name="Negar")).to_have_class("btn-urgente")
    sem_violacao(page)
    dialogo.get_by_role("link", name="Voltar").click()  # desiste: nada foi decidido
    expect(dialogo).to_be_hidden()

    page.get_by_text("Aprovar", exact=True).click()
    page.get_by_role("button", name="Confirmar decisão").click()
    expect(dialogo.get_by_role("button", name="Aprovar")).to_have_class("btn-aprovar")
    page.keyboard.press("Escape")
    expect(dialogo).to_be_hidden()

    page.get_by_text("Negar", exact=True).click()
    page.get_by_role("button", name="Confirmar decisão").click()
    dialogo.get_by_role("button", name="Negar").click()  # sem motivo: o diálogo segura
    expect(dialogo).to_be_visible()
    dialogo.get_by_label("Motivo (obrigatório para negar)").fill("São pessoas diferentes")
    dialogo.get_by_role("button", name="Negar").click()
    expect(page.get_by_role("status")).to_contain_text("Solicitação negada.")
    assert cadastro.pacientes.ver_ficha(recepcao, pid).dados.nome is not None  # negado: o cadastro continua
    assert erros == []
