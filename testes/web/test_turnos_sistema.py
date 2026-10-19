"""Tela inicial no navegador (DD-76): arraste, clique no cartão e teclado movem o paciente entre os quadros; o foco
volta ao cartão movido; confirmação; axe-core (RNF-406) e nenhum erro de script (DD-09).

O relógio do servidor é o de segunda, 19/10/2026, às 09h05: primeiro turno com a confirmação liberada.
"""

from __future__ import annotations

from datetime import date, datetime

import pytest
from playwright.sync_api import Page, expect
from sqlalchemy import Engine, text

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
    return RelogioControlado(datetime(2026, 10, 19, 9, 5, tzinfo=FUSO_CLINICA))


def situacoes(engine: Engine) -> dict[int, str]:
    with engine.connect() as c:
        return {p: s for p, s in c.execute(text("SELECT paciente_id, situacao FROM presenca"))}


@pytest.mark.requisito("DD-76", "RNF-406", "RF-502", "DD-24", "CT-FRQ-03")
def test_quadros_com_arraste_clique_e_teclado(
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
    definir_implantacao(engine_migracao, date(2026, 10, 19), operacao_zerada["ti"])
    (a, _), (b, nome_b), (c, _) = pacientes_no_turno(engine_web, operacao_zerada, fabrica, 3, 1, INICIO)
    criar_usuario("sistturno_rec")
    entrar_no_navegador(page, endereco, "sistturno_rec")

    sessao = page.locator("[data-sessao]")
    presentes, faltantes = sessao.locator('[data-zona="presentes"]'), sessao.locator('[data-zona="faltantes"]')
    expect(sessao.get_by_role("heading", name="Primeiro turno")).to_be_visible()
    expect(sessao.locator(".selo-sessao")).to_have_text("Confirmação liberada")
    expect(presentes.locator("[data-paciente]")).to_have_count(3)
    sem_violacao(page)

    # Arraste: o cartão vai para Faltantes e a exceção é gravada.
    presentes.locator(f'[data-paciente="{a}"]').drag_to(faltantes)
    expect(faltantes.locator(f'[data-paciente="{a}"]')).to_be_visible()
    assert situacoes(engine_web) == {a: "ausente"}

    # Teclado: o botão do cartão; depois da troca do painel, o foco volta ao mesmo cartão.
    page.get_by_role("button", name=f"Mover para faltantes: {nome_b}").focus()
    page.keyboard.press("Enter")
    expect(faltantes.locator(f'[data-paciente="{b}"]')).to_be_visible()
    expect(page.get_by_role("button", name=f"Mover para presentes: {nome_b}")).to_be_focused()

    # Clique em qualquer parte do cartão: volta para Presentes.
    faltantes.locator(f'[data-paciente="{b}"] [data-nome]').click()
    expect(presentes.locator(f'[data-paciente="{b}"]')).to_be_visible()
    assert situacoes(engine_web) == {a: "ausente"}  # de volta ao padrão: sem exceção (DD-24)
    sem_violacao(page)

    page.get_by_role("button", name="Confirmar sessão").click()
    expect(page.locator("[data-mensagem]")).to_contain_text("Sessão confirmada.")
    expect(page.locator("#anuncio-turnos")).to_contain_text("Sessão confirmada.")
    expect(page.locator("[data-sessao]")).to_have_count(0)  # a sessão confirmada sai do painel (DD-76)
    assert situacoes(engine_web) == {a: "ausente", b: "presente", c: "presente"}
    assert erros == []


@pytest.mark.requisito("DD-57", "DD-93", "RNF-406")
def test_atualizacao_automatica_espera_quem_esta_digitando(
    operacao_zerada: dict[str, int],
    criar_usuario: CriarUsuario,
    engine_web: Engine,
    engine_migracao: Engine,
    endereco: str,
    page: Page,
    fabrica: Fabrica,
) -> None:
    definir_implantacao(engine_migracao, date(2026, 10, 19), operacao_zerada["ti"])
    pacientes_no_turno(engine_web, operacao_zerada, fabrica, 1, 1, INICIO)
    automaticas: list[str] = []
    page.on("request", lambda r: automaticas.append(r.url) if r.headers.get("x-sar-automatica") == "1" else None)
    page.clock.install()
    criar_usuario("sistturno_rec2")
    entrar_no_navegador(page, endereco, "sistturno_rec2")

    page.locator("summary", has_text="Acrescentar paciente").click()
    busca = page.get_by_label("Nome, prontuário, CPF ou CNS")
    busca.fill("Mar")
    page.clock.run_for("02:00")
    expect(busca).to_have_value("Mar")  # o painel não foi trocado no meio da digitação
    assert automaticas == []

    page.locator("summary", has_text="Acrescentar paciente").click()  # fecha; o foco fica no resumo, fora de campo
    page.clock.run_for("01:05")
    page.wait_for_timeout(300)
    assert any(url.endswith("/turnos/painel") for url in automaticas)  # com a marca automática (DD-57)
