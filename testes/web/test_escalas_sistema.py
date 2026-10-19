"""Escalas da enfermagem no navegador: axe-core (RNF-406), rótulos e nenhum erro de script (DD-09)."""

from __future__ import annotations

from datetime import datetime

import pytest
from playwright.sync_api import Page, expect
from sqlalchemy import Engine

from sar.modulo_08_dados.relogio import FUSO_CLINICA
from testes.apoio.acesso import CriarUsuario
from testes.apoio.cadastro import INICIO
from testes.apoio.fabrica import Fabrica
from testes.apoio.operacao import definir_implantacao, pacientes_no_turno
from testes.apoio.relogio_controlado import RelogioControlado
from testes.web.conftest import entrar_no_navegador, sem_violacao

pytestmark = pytest.mark.sistema


@pytest.fixture
def relogio_do_servidor() -> RelogioControlado:
    return RelogioControlado(datetime(2026, 10, 19, 10, 0, tzinfo=FUSO_CLINICA))


@pytest.mark.requisito("RNF-406", "RF-405", "RF-503")
def test_distribuicao_e_troca_pelo_navegador(
    operacao_zerada: dict[str, int],
    criar_usuario: CriarUsuario,
    engine_web: Engine,
    engine_migracao: Engine,
    endereco: str,
    page: Page,
    fabrica: Fabrica,
) -> None:
    erros: list[str] = []
    page.on("console", lambda m: erros.append(m.text) if m.type == "error" else None)
    page.on("pageerror", lambda e: erros.append(str(e)))
    definir_implantacao(engine_migracao, INICIO, operacao_zerada["ti"])
    [(_, nome)] = pacientes_no_turno(engine_web, operacao_zerada, fabrica, 1, 1, INICIO)
    criar_usuario("sistesc_enf", perfil="enfermagem")
    entrar_no_navegador(page, endereco, "sistesc_enf")

    page.get_by_role("link", name="Escalas").click()
    expect(page.get_by_role("heading", name="Pacientes por escala")).to_be_visible()
    expect(page.get_by_label(f"Escala de {nome}")).to_have_value("1")
    sem_violacao(page)
    page.get_by_label(f"Escala de {nome}").select_option(label="2-seg")
    page.get_by_role("button", name="Salvar alocações").click()
    expect(page.get_by_role("status")).to_contain_text("1 alocação registrada")

    page.get_by_role("link", name=f"Escala, trocas e extras de {nome}").click()
    sem_violacao(page)
    page.get_by_label("Sessão que vai perder").fill("2026-10-21")
    page.get_by_label("Sessão em que vem").fill("2026-10-22")
    page.get_by_label("Escala em que vem").select_option(label="1-ter")
    page.get_by_role("button", name="Registrar troca").click()
    expect(page.get_by_role("status")).to_contain_text("Troca registrada.")
    expect(page.get_by_text("Declaração a emitir")).to_be_visible()
    sem_violacao(page)
    assert erros == []
