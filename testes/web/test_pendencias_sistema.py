"""Pendências e jobs no navegador: navegação pelo menu e pelo teclado, o bloco da tela inicial, as etiquetas nos
cartões, a tela de jobs do TI; axe-core em cada tela (RNF-406) e nenhum erro de script (DD-09).

O relógio do servidor é o de segunda, 19/10/2026, às 05h30: o primeiro turno está em preparação (DD-30).
"""

from __future__ import annotations

import re
from datetime import date, datetime

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
    return RelogioControlado(datetime(2026, 10, 19, 5, 30, tzinfo=FUSO_CLINICA))


def vigiar_erros(page: Page) -> list[str]:
    erros: list[str] = []
    page.on("console", lambda m: erros.append(m.text) if m.type == "error" else None)
    page.on("pageerror", lambda e: erros.append(str(e)))
    return erros


@pytest.mark.requisito("RF-1010", "RNF-408", "RNF-406", "RF-922", "DD-30", "CT-PEN-03", "CT-PEN-04")
def test_recepcao_do_inicio_as_pendencias(
    operacao_zerada: dict[str, int], criar_usuario: CriarUsuario, engine_web: Engine, engine_migracao: Engine,
    endereco: str, page: Page, fabrica: Fabrica,
) -> None:  # fmt: skip
    erros = vigiar_erros(page)
    definir_implantacao(engine_migracao, date(2026, 10, 19), operacao_zerada["ti"])
    (pid, nome), _ = pacientes_no_turno(engine_web, operacao_zerada, fabrica, 2, 1, INICIO)
    criar_usuario("sistpend_rec")
    entrar_no_navegador(page, endereco, "sistpend_rec")

    resumo = page.locator("#pendencias-resumo")
    expect(resumo.get_by_role("heading", name="Pendências")).to_be_visible()
    expect(resumo.locator('[data-contagem="N"] .numero')).not_to_have_text("0")
    cartao = page.locator(f'[data-paciente="{pid}"]')
    expect(cartao.locator('[data-sobre="pendencias"]')).to_contain_text("Cadastro incompleto")
    sem_violacao(page)

    resumo.locator('[data-contagem="N"]').focus()
    page.keyboard.press("Enter")  # pelo teclado, até a seção da prioridade
    expect(page).to_have_url(f"{endereco}/pendencias#g-N")
    normal = page.locator('[data-prioridade="N"]')
    expect(normal.get_by_role("heading", name="Normal")).to_be_visible()
    expect(normal.get_by_text(f"Cadastro incompleto: {nome}", exact=True)).to_be_visible()
    expect(
        page.get_by_role("navigation", name="Navegação principal").get_by_role("link", name="Pendências")
    ).to_have_attribute("aria-current", "page")
    sem_violacao(page)

    normal.get_by_role("link", name=re.compile(f"^Completar.*Cadastro incompleto: {nome}$")).click()
    expect(page).to_have_url(f"{endereco}/pacientes/{pid}")
    expect(page.get_by_role("heading", name="Outras pendências")).to_be_visible()
    sem_violacao(page)
    assert erros == []


@pytest.mark.requisito("RF-1004", "CT-ACE-02", "DD-112", "RNF-406", "CT-JOB-04")
def test_ti_ve_os_jobs_so_para_leitura(
    operacao_zerada: dict[str, int], criar_usuario: CriarUsuario, engine_web: Engine, engine_migracao: Engine,
    endereco: str, page: Page, fabrica: Fabrica,
) -> None:  # fmt: skip
    erros = vigiar_erros(page)
    definir_implantacao(engine_migracao, date(2026, 10, 1), operacao_zerada["ti"])  # o backup já está atrasado
    pacientes = pacientes_no_turno(engine_web, operacao_zerada, fabrica, 1, 1, INICIO)
    criar_usuario("sistpend_ti", perfil="ti")
    entrar_no_navegador(page, endereco, "sistpend_ti")
    page.get_by_role("link", name="Pendências").click()
    urgencia = page.locator('[data-prioridade="U"]')
    expect(urgencia.get_by_text("Job atrasado", exact=True).first).to_be_visible()
    mais = urgencia.get_by_text(re.compile(r"^Mais \d+ de job atrasado$"))
    expect(mais).to_have_css("list-style-type", "none")  # só a legenda, sem a seta (ajuste aprovado em 10/11/2026)
    mais.focus()  # mais de 5: o resto no <details>
    page.keyboard.press("Enter")
    expect(urgencia.get_by_text("Backup: dump e restic", exact=False)).to_be_visible()
    sem_violacao(page)
    urgencia.get_by_role("link", name="Ver os jobs").first.click()
    expect(page.get_by_role("heading", name="Situação de cada job")).to_be_visible()
    expect(page.locator('[data-job="backup"]')).to_contain_text("Atrasado")
    expect(page.locator("main").get_by_role("button")).to_have_count(0)  # só leitura (DD-112)
    sem_violacao(page)
    assert all(nome not in page.content() for _, nome in pacientes)
    assert erros == []
