"""Frequência do mês na ficha, pela web e com o banco: RF-916, RF-918, DD-25, DD-26.

O paciente é do primeiro turno de terça, quinta e sábado; faltou em 06/10 e 08/10 e veio fora da escala em 07/10 e
09/10. O relógio é o de terça, 13/10/2026, às 10h.
"""

from __future__ import annotations

import re
from datetime import date, datetime

import pytest
from flask.testing import FlaskClient
from sqlalchemy import Engine, text

from sar.modulo_08_dados.relogio import FUSO_CLINICA
from sar.nucleo.contexto import Perfil
from testes.apoio.acesso import CriarUsuario
from testes.apoio.cadastro import INICIO
from testes.apoio.fabrica import Fabrica
from testes.apoio.operacao import confirmar, contexto, definir_implantacao, local, pacientes_no_turno
from testes.apoio.operacao import montar as montar_operacao
from testes.apoio.relogio_controlado import RelogioControlado
from testes.apoio.web import get, logado, montar, post

pytestmark = pytest.mark.integracao

SEG_1, TER_1 = 1, 2


@pytest.fixture
def relogio() -> RelogioControlado:
    return RelogioControlado(datetime(2026, 10, 13, 10, 0, tzinfo=FUSO_CLINICA))


def preparar(engine: Engine, ids: dict[str, int], fabrica: Fabrica, faltas: list[date], fora: list[date]) -> int:
    op = montar_operacao(engine)
    [(pid, _)] = pacientes_no_turno(engine, ids, fabrica, 1, TER_1, date(2026, 9, 1))
    for dia in faltas:
        op.turnos.marcar_ausencia(contexto(ids, "recepcao", Perfil.RECEPCAO, local(dia, 9)), dia, TER_1, pid)
        confirmar(op, ids, dia, TER_1)
    for dia in fora:
        op.turnos.acrescentar_paciente(contexto(ids, "recepcao", Perfil.RECEPCAO, local(dia, 7)), dia, SEG_1, pid)
    return pid


def cliente(engine: Engine, criar_usuario: CriarUsuario, relogio: RelogioControlado, perfil: str) -> FlaskClient:
    login = f"webfreq_{perfil[:5]}"
    criar_usuario(login, perfil=perfil)
    return logado(montar(engine, relogio=relogio), login)


def opcoes(html: str, nome: str) -> list[str]:
    bloco = re.search(rf'name="{nome}">(.*?)</select>', html, re.S)
    assert bloco, html[:200]
    return re.findall(r'value="(\d+)"', bloco.group(1))


@pytest.mark.requisito("RF-916", "RF-918", "DD-25")
def test_ficha_mostra_o_balanco_e_refaz_o_pareamento(
    operacao_zerada: dict[str, int],
    criar_usuario: CriarUsuario,
    engine_web: Engine,
    engine_migracao: Engine,
    relogio: RelogioControlado,
    fabrica: Fabrica,
) -> None:
    definir_implantacao(engine_migracao, INICIO, operacao_zerada["ti"])
    pid = preparar(engine_web, operacao_zerada, fabrica, [date(2026, 10, 6), date(2026, 10, 8)],
                   [date(2026, 10, 7), date(2026, 10, 9)])  # fmt: skip
    recepcao = cliente(engine_web, criar_usuario, relogio, "recepcao")
    html = get(recepcao, f"/pacientes/{pid}").get_data(as_text=True)
    assert "Frequência de 10/2026" in html and html.count("Automático, pela ordem das datas") == 2
    assert "Mês aberto" in html and "?competencia=2026-09" in html
    cartoes = re.findall(r'bg-freq-([a-z-]+)" data-balanco="\d"><dt class="text-sm text-suave">([^<]+)</dt>', html)
    assert cartoes == [("previstas", "Previstas"), ("realizadas", "Realizadas"),
                       ("ausencias", "Ausências não compensadas"), ("reposicoes", "Reposições"),
                       ("extras", "Extras provisórias"), ("a-realizar", "A realizar")]  # fmt: skip
    ausencias, presencas = opcoes(html, "ausencia_id"), opcoes(html, "presenca_id")
    assert len(ausencias) == 2 and len(presencas) == 2

    ligado = post(recepcao, f"/pacientes/{pid}/frequencia/ligar",
                  {"competencia": "2026-10", "ausencia_id": ausencias[0], "presenca_id": presencas[1]})  # fmt: skip
    assert ligado.status_code == 302 and "resultado=pareamento" in ligado.headers["Location"]
    depois = get(recepcao, f"/pacientes/{pid}?competencia=2026-10").get_data(as_text=True)
    assert "Ligação da recepção" in depois and depois.count("Automático, pela ordem das datas") == 1
    desfeito = post(recepcao, f"/pacientes/{pid}/frequencia/desfazer",
                    {"competencia": "2026-10", "ausencia_id": ausencias[0], "presenca_id": presencas[1]})  # fmt: skip
    assert desfeito.status_code == 302
    assert "Ligação da recepção" not in get(recepcao, f"/pacientes/{pid}").get_data(as_text=True)

    visualizador = cliente(engine_web, criar_usuario, relogio, "visualizador")
    so_ve = get(visualizador, f"/pacientes/{pid}").get_data(as_text=True)
    assert "Frequência de 10/2026" in so_ve and "Refazer o pareamento" not in so_ve
    dados = {"competencia": "2026-10", "ausencia_id": ausencias[0], "presenca_id": presencas[1]}
    assert post(visualizador, f"/pacientes/{pid}/frequencia/ligar", dados).status_code == 403


@pytest.mark.requisito("DD-26", "RF-918", "DEC-42")
def test_em_mes_fechado_refazer_vira_pedido_de_autorizacao(
    operacao_zerada: dict[str, int],
    criar_usuario: CriarUsuario,
    engine_web: Engine,
    engine_migracao: Engine,
    relogio: RelogioControlado,
    fabrica: Fabrica,
) -> None:
    definir_implantacao(engine_migracao, date(2026, 9, 28), operacao_zerada["ti"])
    pid = preparar(engine_web, operacao_zerada, fabrica, [date(2026, 9, 29)], [date(2026, 9, 28)])
    op = montar_operacao(engine_web)
    for dia, escalas in ((date(2026, 9, 28), (1, 3, 5)), (date(2026, 9, 29), (4, 6)), (date(2026, 9, 30), (1, 3, 5))):
        for escala in escalas:
            confirmar(op, operacao_zerada, dia, escala)  # setembro inteiro confirmado: fechado
    recepcao = cliente(engine_web, criar_usuario, relogio, "recepcao")
    html = get(recepcao, f"/pacientes/{pid}?competencia=2026-09").get_data(as_text=True)
    assert "Mês fechado" in html and "Automático, pela ordem das datas" in html
    dados = {"competencia": "2026-09", "ausencia_id": opcoes(html, "ausencia_id")[0],
             "presenca_id": opcoes(html, "presenca_id")[0]}  # fmt: skip
    recusa = post(recepcao, f"/pacientes/{pid}/frequencia/ligar", dados).get_data(as_text=True)
    assert "precisa de autorização da administração" in recusa and "Pedir autorização" in recusa
    ligacoes = re.search(r'name="ligacoes" value="([\d;-]+)"', recusa)
    assert ligacoes is not None
    envio = {"competencia": "2026-09", "ligacoes": ligacoes.group(1), "motivo": "Ajuste do faturamento"}
    pedido = post(recepcao, f"/pacientes/{pid}/frequencia/pedir", envio)
    assert pedido.status_code == 302 and "pedido_pareamento" in pedido.headers["Location"]
    with engine_web.connect() as c:
        assert tuple(c.execute(text("SELECT tipo, estado FROM solicitacao_autorizacao")).one()) == (
            "operacao.pareamento.refazer", "pendente",
        )  # fmt: skip
