"""Calendário próprio, em português (DD-108), no navegador: o recorte de datas num seletor só, a data avulsa e o mês,
pelo mouse, pelo teclado e com o axe-core com o calendário aberto (RNF-406). O valor ISO continua indo ao servidor."""

from __future__ import annotations

import os
import re
from pathlib import Path

import pytest
from playwright.sync_api import Page, expect
from sqlalchemy import Engine

from testes.apoio.acesso import CriarUsuario
from testes.web.conftest import entrar_no_navegador, sem_violacao

pytestmark = pytest.mark.sistema
# Os campos do formulário de filtros: os botões de exportar do relatório já gerado levam cópias escondidas deles.
FILTROS = 'form[aria-label="Filtros do relatório"]'


def capturar(page: Page, nome: str) -> None:
    pasta = os.environ.get("SAR_CAPTURAS")
    if pasta:
        for largura in (1900, 1100, 700):
            page.set_viewport_size({"width": largura, "height": 1000})
            page.screenshot(path=str(Path(pasta) / f"{nome}-{largura}.png"), full_page=True)
        page.set_viewport_size({"width": 1280, "height": 900})


@pytest.mark.requisito("DD-108", "RF-901", "RNF-406")
def test_periodo_escolhido_no_mesmo_calendario_pelo_mouse_e_pelo_teclado(
    criar_usuario: CriarUsuario, endereco: str, page: Page, trilha_zerada: Engine
) -> None:
    criar_usuario("sisi_admin", perfil="administracao")
    entrar_no_navegador(page, endereco, "sisi_admin")
    page.goto(f"{endereco}/relatorios/entradas")
    expect(page.get_by_label("De", exact=True)).to_be_hidden()  # os dois campos ficam escondidos, mas no formulário
    seletor = page.get_by_role("button", name="Período")
    seletor.click()
    calendario = page.get_by_role("dialog", name="Escolher período")
    expect(calendario).to_be_visible()
    sem_violacao(page)

    # Mouse: volta ao mês anterior e escolhe o fim antes do início; o seletor põe em ordem.
    calendario.get_by_role("button", name="Mês anterior").click()
    titulo = calendario.get_by_role("heading").inner_text()
    mes, ano = titulo.split(" de ")
    calendario.get_by_role("button", name=f"20 de {mes} de {ano}", exact=True).click()
    expect(calendario.get_by_text("Agora escolha o último dia.", exact=False)).to_be_visible()
    capturar(page, "intervalo-escolhendo")
    calendario.get_by_role("button", name=f"3 de {mes} de {ano}", exact=True).click()
    expect(calendario).to_be_hidden()
    inicio, fim = (
        page.locator(FILTROS + ' input[name="inicio"]').input_value(),
        page.locator(FILTROS + ' input[name="fim"]').input_value(),
    )
    assert inicio.endswith("-03") and fim.endswith("-20") and inicio[:7] == fim[:7]
    expect(seletor).to_have_text(f"03/{inicio[5:7]}/{inicio[:4]} – 20/{fim[5:7]}/{fim[:4]}")
    expect(seletor).to_be_focused()

    # Teclado: abre no início escolhido, anda um dia, escolhe, desce uma semana, troca de mês e escolhe o fim.
    seletor.press("Enter")
    page.keyboard.press("ArrowRight")
    page.keyboard.press("Enter")
    page.keyboard.press("PageDown")
    page.keyboard.press("Enter")
    assert page.locator(FILTROS + ' input[name="inicio"]').input_value().endswith("-04")
    assert page.locator(FILTROS + ' input[name="fim"]').input_value().endswith("-04")
    assert (
        page.locator(FILTROS + ' input[name="fim"]').input_value()[:7]
        > page.locator(FILTROS + ' input[name="inicio"]').input_value()[:7]
    )
    page.keyboard.press("Tab")  # sai do seletor; o formulário segue pelo teclado
    page.get_by_role("button", name="Gerar relatório").click()
    expect(page.get_by_role("table", name="Entradas de pacientes por período")).to_be_visible()
    expect(page.get_by_role("button", name="Período")).to_contain_text("04/")  # o período volta escolhido
    seletor = page.get_by_role("button", name="Período")
    seletor.click()
    page.keyboard.press("Escape")
    expect(page.get_by_role("dialog", name="Escolher período")).to_be_hidden()
    capturar(page, "intervalo-relatorio")

    page.goto(f"{endereco}/trilha")
    page.get_by_role("button", name="Período").click()
    page.get_by_role("dialog", name="Escolher período").get_by_role("button", name="Este mês").click()
    assert page.locator('input[name="de"]').input_value().endswith("-01")
    sem_violacao(page)


@pytest.mark.requisito("DD-108", "RF-906", "RNF-406")
def test_mes_e_data_avulsa_no_calendario_em_portugues(
    criar_usuario: CriarUsuario, endereco: str, page: Page, trilha_zerada: Engine
) -> None:
    criar_usuario("sisi_admin2", perfil="administracao")
    entrar_no_navegador(page, endereco, "sisi_admin2")

    # Mês: o quadro com os doze meses; a seta troca o ano.
    page.goto(f"{endereco}/relatorios/frequencia_mensal")
    seletor = page.get_by_role("button", name="Mês")
    expect(seletor).to_have_text(re.compile(r"^[a-zç]+ de \d{4}$"))
    seletor.click()
    quadro = page.get_by_role("dialog", name="Escolher mês")
    expect(quadro).to_be_visible()
    sem_violacao(page)
    capturar(page, "calendario-mes")
    ano = int(quadro.get_by_role("heading").inner_text())
    quadro.get_by_role("button", name="Ano anterior").click()
    quadro.get_by_role("button", name=f"março de {ano - 1}", exact=True).click()
    expect(quadro).to_be_hidden()
    expect(page.locator(FILTROS + ' input[name="competencia"]')).to_have_value(f"{ano - 1}-03")
    expect(seletor).to_have_text(f"março de {ano - 1}")
    expect(seletor).to_be_focused()

    # Data avulsa: digitada como dd/mm/aaaa, com a data ISO no campo escondido; data impossível não passa.
    page.goto(f"{endereco}/relatorios/ocupacao")
    campo = page.get_by_role("combobox", name="Data de referência")
    oculto = page.locator(FILTROS + ' input[type="hidden"][name="data"]')
    campo.fill("31022026")
    expect(campo).to_have_value("31/02/2026")
    assert "dd/mm/aaaa" in campo.evaluate("(c) => c.validationMessage")
    expect(oculto).to_have_value("")
    campo.fill("30/10/2026")
    expect(oculto).to_have_value("2026-10-30")

    # Pelo calendário: o clique abre sem tirar o foco do campo; a seta para baixo entra nos dias.
    campo.click()
    calendario = page.get_by_role("dialog", name="Escolher data de referência")
    expect(calendario).to_be_visible()
    expect(calendario.get_by_role("heading")).to_have_text("outubro de 2026")
    sem_violacao(page)
    capturar(page, "calendario-dia")
    campo.press("ArrowDown")
    expect(calendario.get_by_role("button", name="30 de outubro de 2026", exact=True)).to_be_focused()
    page.keyboard.press("ArrowRight")
    page.keyboard.press("Enter")
    expect(calendario).to_be_hidden()
    expect(campo).to_have_value("31/10/2026")
    expect(oculto).to_have_value("2026-10-31")
    page.get_by_role("button", name="Gerar relatório").click()
    # A ocupação em blocos: um por escala, com a lista rolável pelo teclado e o total no rodapé, e o total geral.
    expect(page.get_by_role("region", name="Pacientes: Primeiro turno — segunda, quarta e sexta")).to_be_visible()
    expect(page.locator("[data-bloco]")).to_have_count(6 + page.get_by_role("heading", name="Sem alocação").count())
    expect(page.locator("[data-total-geral]")).to_contain_text("Total geral:")
    sem_violacao(page)
    expect(page.get_by_role("combobox", name="Data de referência")).to_have_value("31/10/2026")
