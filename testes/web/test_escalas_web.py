"""Escalas da enfermagem pela web, com o banco: RF-402 a RF-406, RF-503, RF-504, RF-921, DD-75 e o pedido de
autorização quando alcança sessão confirmada (DEC-42). O relógio é o de segunda, 19/10/2026, às 10h."""

from __future__ import annotations

import re
from datetime import date, datetime

import pytest
from flask.testing import FlaskClient
from sqlalchemy import Engine, text

from sar.modulo_08_dados.relogio import FUSO_CLINICA
from sar.nucleo.contexto import Perfil
from testes.apoio.acesso import CriarUsuario
from testes.apoio.cadastro import INICIO, dados_completos
from testes.apoio.fabrica import Fabrica
from testes.apoio.operacao import confirmar_direto, contexto, definir_implantacao, local, pacientes_no_turno
from testes.apoio.operacao import montar as montar_operacao
from testes.apoio.relogio_controlado import RelogioControlado
from testes.apoio.web import get, logado, montar, post

pytestmark = pytest.mark.integracao


@pytest.fixture
def relogio() -> RelogioControlado:
    return RelogioControlado(datetime(2026, 10, 19, 10, 0, tzinfo=FUSO_CLINICA))


@pytest.fixture
def pacientes(
    operacao_zerada: dict[str, int], engine_web: Engine, engine_migracao: Engine, fabrica: Fabrica
) -> list[tuple[int, str]]:
    definir_implantacao(engine_migracao, INICIO, operacao_zerada["ti"])
    return pacientes_no_turno(engine_web, operacao_zerada, fabrica, 2, 1, INICIO)


def cliente(engine: Engine, criar_usuario: CriarUsuario, relogio: RelogioControlado, perfil: str) -> FlaskClient:
    login = f"webesc_{perfil[:5]}"
    criar_usuario(login, perfil=perfil)
    return logado(montar(engine, relogio=relogio), login)


def alocacoes(engine: Engine) -> list[tuple[int, object, date]]:
    with engine.connect() as c:
        sql = (
            "SELECT p.paciente_id, a.escala_id, a.vigencia_inicio FROM alocacao a"
            " JOIN periodo_tratamento p ON p.id = a.periodo_id ORDER BY a.id"
        )
        return [tuple(r) for r in c.execute(text(sql))]


@pytest.mark.requisito("RF-404", "RF-405", "RF-406", "DD-75")
def test_enfermagem_ve_a_contagem_e_distribui_em_lote(
    pacientes: list[tuple[int, str]], criar_usuario: CriarUsuario, engine_web: Engine, relogio: RelogioControlado
) -> None:
    enfermagem = cliente(engine_web, criar_usuario, relogio, "enfermagem")
    assert 'href="/escalas"' in get(enfermagem, "/").get_data(as_text=True)
    html = get(enfermagem, "/escalas").get_data(as_text=True)
    assert all(codigo in html for codigo in ("1-seg", "1-ter", "2-seg", "2-ter", "3-seg", "3-ter"))  # só aqui (DD-75)
    (a, nome_a), (b, _) = pacientes
    assert re.search(r'data-contagem="1">2<', html)  # quadro do 1-seg com os dois
    seletor = re.search(rf'aria-label="Turno de {re.escape(nome_a)}"(.*?)</select>', html, re.S)
    assert seletor and re.findall(r">(\d-\w{3})<", seletor.group(1)) == [
        "1-seg",
        "2-seg",
        "3-seg",
        "1-ter",
        "2-ter",
        "3-ter",
    ]
    assert 'name="data"' in html.split("<main", 1)[0]  # data de referência no cabeçalho, junto do título
    assert re.search(r'data-contagem="sem">0<', html)
    assert f'aria-label="Turno de {nome_a}"' in html and "Salvar alocações" in html and "Acrescentar a 1-seg" in html

    nada = post(enfermagem, "/escalas/lote", {f"escala-{a}": "1", f"atual-{a}": "1", "inicio": "2026-10-19"})
    assert "Nenhuma escala foi mudada." in nada.get_data(as_text=True)
    resposta = post(
        enfermagem, "/escalas/lote",
        {f"escala-{a}": "4", f"atual-{a}": "1", f"escala-{b}": "", f"atual-{b}": "1", "inicio": "2026-10-20"},
    )  # fmt: skip
    assert resposta.status_code == 302 and "resultado=2" in resposta.headers["Location"]
    assert alocacoes(engine_web)[-2:] == [(a, 4, date(2026, 10, 20)), (b, None, date(2026, 10, 20))]
    depois = get(enfermagem, "/escalas?data=2026-10-20").get_data(as_text=True)
    assert re.search(r'data-contagem="sem">1<', depois) and re.search(r'data-contagem="4">1<', depois)


@pytest.mark.requisito("RF-503", "RF-504", "P-11", "RF-809")
def test_trocas_e_extras_pela_pagina_do_paciente(
    pacientes: list[tuple[int, str]], criar_usuario: CriarUsuario, engine_web: Engine, relogio: RelogioControlado
) -> None:
    enfermagem = cliente(engine_web, criar_usuario, relogio, "enfermagem")
    pid = pacientes[0][0]
    pagina = f"/escalas/pacientes/{pid}"
    assert "Desde 01/10/2026: 1-seg" in get(enfermagem, pagina).get_data(as_text=True)
    meses = post(
        enfermagem, f"{pagina}/troca", {"origem": "2026-10-30", "destino": "2026-11-03", "escala_destino_id": "2"}
    )
    assert "A troca precisa ficar no mesmo mês" in meses.get_data(as_text=True)
    feita = post(
        enfermagem, f"{pagina}/troca", {"origem": "2026-10-21", "destino": "2026-10-22", "escala_destino_id": "2"}
    )
    assert feita.status_code == 302
    html = get(enfermagem, pagina).get_data(as_text=True)
    assert "De 21/10 para 22/10, 1-ter" in html and "Declaração a emitir" in html
    post(enfermagem, f"{pagina}/extra", {"data": "2026-10-24", "escala_id": "2"})
    extra = re.search(r'data-extra="(\d+)"', get(enfermagem, pagina).get_data(as_text=True))
    assert extra is not None
    assert post(enfermagem, f"{pagina}/extra/{extra.group(1)}/cancelar", {}).status_code == 302
    assert "Nenhuma extra neste mês ou depois." in get(enfermagem, pagina).get_data(as_text=True)


@pytest.mark.requisito("DEC-42", "RF-1008", "DD-26")
def test_alocacao_que_alcanca_sessao_confirmada_oferece_o_pedido(
    pacientes: list[tuple[int, str]],
    criar_usuario: CriarUsuario,
    engine_web: Engine,
    relogio: RelogioControlado,
    operacao_zerada: dict[str, int],
) -> None:
    confirmar_direto(engine_web, date(2026, 10, 12), 1, operacao_zerada["recepcao"])
    enfermagem = cliente(engine_web, criar_usuario, relogio, "enfermagem")
    pid = pacientes[0][0]
    recusa = post(enfermagem, f"/escalas/pacientes/{pid}/alocar", {"escala_id": "3", "inicio": "2026-10-05"})
    html = recusa.get_data(as_text=True)
    assert "precisa de autorização da administração" in html and "Pedir autorização" in html
    assert 'name="acao" value="alocar"' in html and 'name="inicio" value="2026-10-05"' in html
    dados = {"acao": "alocar", "escala_id": "3", "inicio": "2026-10-05", "motivo": "Escala errada desde o início"}
    pedido = post(enfermagem, f"/escalas/pacientes/{pid}/pedir", dados)
    assert pedido.status_code == 302 and "Pedido" in pedido.headers["Location"]
    with engine_web.connect() as c:
        tipo = c.execute(text("SELECT tipo, estado FROM solicitacao_autorizacao")).one()
    assert tuple(tipo) == ("operacao.alocacao.registrar_retroativa", "pendente")


@pytest.mark.requisito("RF-921", "DEC-48")
def test_enfermagem_registra_a_ciencia_da_presenca_acrescentada(
    pacientes: list[tuple[int, str]],
    criar_usuario: CriarUsuario,
    engine_web: Engine,
    relogio: RelogioControlado,
    operacao_zerada: dict[str, int],
) -> None:
    op = montar_operacao(engine_web)
    pid, nome = pacientes[1]
    dia = date(2026, 10, 13)  # terça: fora da escala dele (segunda, quarta e sexta)
    op.turnos.acrescentar_paciente(contexto(operacao_zerada, "recepcao", Perfil.RECEPCAO, local(dia, 7)), dia, 2, pid)
    enfermagem = cliente(engine_web, criar_usuario, relogio, "enfermagem")
    html = get(enfermagem, "/escalas").get_data(as_text=True)
    achado = re.search(r'name="presenca_id" value="(\d+)"', html)
    assert achado and f"Registrar ciência: {nome}, 13/10" in html
    resposta = post(enfermagem, "/escalas/ciencia", {"presenca_id": achado.group(1)})
    assert resposta.status_code == 302
    assert "Nenhuma presença pendente de ciência." in get(enfermagem, "/escalas").get_data(as_text=True)


@pytest.mark.requisito("RF-406", "CT-ACE-01", "RNF-625")
def test_recepcao_so_consulta_e_o_ti_nao_ve(
    pacientes: list[tuple[int, str]], criar_usuario: CriarUsuario, engine_web: Engine, relogio: RelogioControlado
) -> None:
    recepcao = cliente(engine_web, criar_usuario, relogio, "recepcao")
    html = get(recepcao, "/escalas").get_data(as_text=True)
    assert "1-seg" in html and "Salvar alocações" not in html and "Presenças fora da escala" not in html
    assert 'data-travado="true"' in html and "Acrescentar a 1-seg" not in html and 'name="escala-' not in html
    pid = pacientes[0][0]
    assert "Registrar troca" not in get(recepcao, f"/escalas/pacientes/{pid}").get_data(as_text=True)
    assert (
        post(recepcao, "/escalas/lote", {f"escala-{pid}": "2", f"atual-{pid}": "1", "inicio": "2026-10-20"}).status_code
        == 403
    )
    assert (
        post(recepcao, f"/escalas/pacientes/{pid}/extra", {"data": "2026-10-24", "escala_id": "2"}).status_code == 403
    )
    ti = cliente(engine_web, criar_usuario, relogio, "ti")
    assert 'href="/escalas"' not in get(ti, "/").get_data(as_text=True)
    assert get(ti, "/escalas").status_code == 403


@pytest.mark.requisito("RF-405")
def test_lote_com_erro_nao_grava_nada_e_mantem_as_escolhas(
    pacientes: list[tuple[int, str]],
    criar_usuario: CriarUsuario,
    engine_web: Engine,
    relogio: RelogioControlado,
    operacao_zerada: dict[str, int],
    fabrica: Fabrica,
) -> None:
    op = montar_operacao(engine_web)
    tardio = op.cadastro.pacientes.criar(contexto(operacao_zerada, "recepcao", Perfil.RECEPCAO),
                                         dados_completos(fabrica), date(2026, 10, 25))  # fmt: skip
    enfermagem = cliente(engine_web, criar_usuario, relogio, "enfermagem")
    a = pacientes[0][0]
    envio = {
        f"escala-{a}": "4",
        f"atual-{a}": "1",
        f"escala-{tardio}": "2",
        f"atual-{tardio}": "",
        "inicio": "2026-10-20",
    }
    html = post(enfermagem, "/escalas/lote", envio).get_data(as_text=True)
    assert "Nada foi gravado." in html
    assert len(alocacoes(engine_web)) == 2  # só as da preparação
    cartao = re.search(rf'data-paciente="{a}".*?</li>', html, re.S)
    assert cartao is not None and "data-mudou" in cartao.group(0) and 'value="4" selected' in cartao.group(0)
