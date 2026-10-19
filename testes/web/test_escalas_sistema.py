"""Escalas da enfermagem no navegador (RF-405): a linha arrastada vira cartão no turno, o seletor e o autocompletar
movem, nada grava até salvar; axe-core (RNF-406) e nenhum erro de script (DD-09)."""

from __future__ import annotations

from datetime import datetime

import pytest
from playwright.sync_api import Page, expect
from sqlalchemy import Engine, text

from sar.modulo_08_dados.relogio import FUSO_CLINICA
from sar.nucleo.contexto import Perfil
from testes.apoio.acesso import CriarUsuario
from testes.apoio.cadastro import INICIO, dados_completos
from testes.apoio.fabrica import Fabrica
from testes.apoio.operacao import contexto, definir_implantacao, montar, pacientes_no_turno
from testes.apoio.relogio_controlado import RelogioControlado
from testes.web.conftest import entrar_no_navegador, sem_violacao

pytestmark = pytest.mark.sistema


@pytest.fixture
def relogio_do_servidor() -> RelogioControlado:
    return RelogioControlado(datetime(2026, 10, 19, 10, 0, tzinfo=FUSO_CLINICA))


def escalas(engine: Engine) -> dict[int, object]:
    """A escala de cada paciente na vigência mais recente."""
    with engine.connect() as c:
        sql = ("SELECT p.paciente_id, a.escala_id FROM alocacao a JOIN periodo_tratamento p ON p.id = a.periodo_id"
               " ORDER BY a.vigencia_inicio, a.id")  # fmt: skip
        return {pid: escala for pid, escala in c.execute(text(sql))}


@pytest.mark.requisito("RNF-406", "RF-405", "RF-403", "RF-503")
def test_distribuicao_por_arraste_seletor_e_autocompletar(
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
    [(alocado, nome_alocado)] = pacientes_no_turno(engine_web, operacao_zerada, fabrica, 1, 1, INICIO)
    recepcao = contexto(operacao_zerada, "recepcao", Perfil.RECEPCAO)
    novos = [dados_completos(fabrica) for _ in range(2)]
    sem = [montar(engine_web).cadastro.pacientes.criar(recepcao, d, INICIO) for d in novos]
    criar_usuario("sistesc_enf", perfil="enfermagem")
    page.set_viewport_size({"width": 1280, "height": 1600})  # o arraste automatizado não rola a página
    entrar_no_navegador(page, endereco, "sistesc_enf")

    page.get_by_role("link", name="Escalas").click()
    lista = page.locator('[data-zona="sem"]')
    quadro_1seg, quadro_2ter = page.locator('[data-lista="1"]'), page.locator('[data-lista="4"]')
    expect(lista.locator(".cartao-escala")).to_have_count(2)
    expect(quadro_1seg.locator(".cartao-escala")).to_have_count(1)
    expect(page.locator('[data-contagem="sem"]')).to_have_text("2")
    sem_violacao(page)

    # Arraste: a linha vira cartão no quadro do 1-seg, marcada como não salva.
    lista.locator(f'[data-paciente="{sem[0]}"] [data-nome]').drag_to(
        page.locator('[data-zona="1"]')
    )  # pelo nome: o seletor não inicia arraste
    cartao = quadro_1seg.locator(f'[data-paciente="{sem[0]}"]')
    expect(cartao).to_be_visible()
    expect(cartao.get_by_text("Não salvo")).to_be_visible()
    expect(page.locator('[data-contagem="1"]')).to_have_text("2")

    # Seletor do cartão (o caminho do teclado): o paciente já alocado vai para o 2-ter.
    page.get_by_label(f"Turno de {nome_alocado}").select_option(label="2-ter")
    expect(quadro_2ter.locator(f'[data-paciente="{alocado}"]')).to_be_visible()

    # Autocompletar do turno: o outro sem alocação entra no 2-ter pelo nome.
    page.get_by_label("Acrescentar a 2-ter").fill(f"{novos[1].nome} · ")
    page.get_by_label("Acrescentar a 2-ter").press_sequentially(novos[1].prontuario or "")
    expect(quadro_2ter.locator(f'[data-paciente="{sem[1]}"]')).to_be_visible()
    expect(page.locator("[data-pendentes]")).to_have_text("3 mudanças não salvas")
    expect(page.locator('[data-vazio="sem"]')).to_be_visible()
    assert escalas(engine_web) == {alocado: 1}  # nada gravado ainda
    sem_violacao(page)

    page.get_by_label("A partir de").fill("2026-10-20")
    page.get_by_role("button", name="Salvar alocações").click()
    expect(page.get_by_role("status")).to_contain_text("3 alocações registradas")
    assert escalas(engine_web) == {alocado: 4, sem[0]: 1, sem[1]: 4}
    expect(page.locator(".cartao-escala[data-mudou]")).to_have_count(0)
    assert erros == []
