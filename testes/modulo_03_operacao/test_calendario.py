"""Calendário e estado da sessão pelo relógio (DDS §7.3): CT-FRQ-02, DD-23, DD-30, DD-32, DD-91."""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from sar.modulo_03_operacao.calendario import (
    CONFIRMAVEIS,
    MARCAVEIS,
    Antecedencias,
    Sessao,
    estado,
    existe,
    limites_da_competencia,
    sessoes_entre,
)
from sar.modulo_03_operacao.contrato import EstadoSessao
from testes.apoio.operacao import ESCALAS, PADRAO, POR_CODIGO, local

SEGUNDA = date(2026, 10, 19)
TERCA = date(2026, 10, 20)
DOMINGO = date(2026, 10, 18)
UM_SEGUNDO = timedelta(seconds=1)


@pytest.mark.requisito("CT-FRQ-02", "DD-30", "DD-32")
@pytest.mark.parametrize(
    ("codigo", "preparacao", "inicio", "liberacao", "fim"),
    [("1-seg", 5, 6, 9, 10), ("2-seg", 10, 11, 14, 15), ("3-seg", 15, 16, 19, 20)],
)
def test_estado_em_cada_minuto_limite(codigo: str, preparacao: int, inicio: int, liberacao: int, fim: int) -> None:
    sessao = Sessao(SEGUNDA, POR_CODIGO[codigo])
    limites = [
        (preparacao, EstadoSessao.FUTURA, EstadoSessao.EM_PREPARACAO),
        (inicio, EstadoSessao.EM_PREPARACAO, EstadoSessao.DEVIDA),
        (liberacao, EstadoSessao.DEVIDA, EstadoSessao.CONFIRMACAO_LIBERADA),
        (fim, EstadoSessao.CONFIRMACAO_LIBERADA, EstadoSessao.URGENCIA),
    ]
    for hora, antes, depois in limites:
        assert estado(sessao, local(SEGUNDA, hora) - UM_SEGUNDO, PADRAO) is antes, (hora, "antes")
        assert estado(sessao, local(SEGUNDA, hora), PADRAO) is depois, (hora, "no minuto")
    assert estado(sessao, local(SEGUNDA + timedelta(days=3), 12), PADRAO) is EstadoSessao.URGENCIA  # dias depois


@pytest.mark.requisito("DD-30", "DD-32")
def test_antecedencias_seguem_o_parametro() -> None:
    sessao = Sessao(SEGUNDA, POR_CODIGO["2-seg"])
    curtas = Antecedencias.em_minutos(15, 30)
    assert estado(sessao, local(SEGUNDA, 10, 44), curtas) is EstadoSessao.FUTURA
    assert estado(sessao, local(SEGUNDA, 10, 45), curtas) is EstadoSessao.EM_PREPARACAO
    assert estado(sessao, local(SEGUNDA, 14, 29), curtas) is EstadoSessao.DEVIDA
    assert estado(sessao, local(SEGUNDA, 14, 30), curtas) is EstadoSessao.CONFIRMACAO_LIBERADA


@pytest.mark.requisito("CT-FRQ-02", "P-12")
def test_confirmada_e_nao_realizada_valem_sobre_o_relogio() -> None:
    sessao = Sessao(SEGUNDA, POR_CODIGO["1-seg"])
    cedo = local(SEGUNDA, 4)
    assert estado(sessao, cedo, PADRAO, confirmada=True) is EstadoSessao.CONFIRMADA
    assert estado(sessao, cedo, PADRAO, confirmada=True, nao_realizada=True) is EstadoSessao.NAO_REALIZADA


@pytest.mark.requisito("P-13", "DD-32")
def test_marcar_a_partir_da_preparacao_e_confirmar_so_na_ultima_hora() -> None:
    assert EstadoSessao.FUTURA not in MARCAVEIS and EstadoSessao.CONFIRMADA not in MARCAVEIS
    assert {EstadoSessao.EM_PREPARACAO, EstadoSessao.URGENCIA} <= MARCAVEIS
    assert {EstadoSessao.CONFIRMACAO_LIBERADA, EstadoSessao.URGENCIA} == CONFIRMAVEIS


@pytest.mark.requisito("DEC-52", "DD-23")
def test_dias_das_escalas_e_domingo_sem_sessao() -> None:
    assert [e.codigo for e in ESCALAS if e.atende(SEGUNDA)] == ["1-seg", "2-seg", "3-seg"]
    assert [e.codigo for e in ESCALAS if e.atende(TERCA)] == ["1-ter", "2-ter", "3-ter"]
    assert not any(e.atende(DOMINGO) for e in ESCALAS)
    assert [e.rotulo for e in ESCALAS[::2]] == ["Primeiro turno", "Segundo turno", "Terceiro turno"]  # DD-75


@pytest.mark.requisito("DD-91", "RN-05")
def test_sem_implantacao_ou_antes_dela_nao_ha_sessao() -> None:
    escala = POR_CODIGO["1-seg"]
    assert not existe(SEGUNDA, escala, None)
    assert not existe(SEGUNDA, escala, SEGUNDA + timedelta(days=1))
    assert existe(SEGUNDA, escala, SEGUNDA)
    assert sessoes_entre(ESCALAS, SEGUNDA, TERCA, None) == []


@pytest.mark.requisito("DD-23", "RF-918")
def test_sessoes_entre_em_ordem_cronologica() -> None:
    sessoes = sessoes_entre(reversed(ESCALAS), DOMINGO, TERCA, implantacao=TERCA)
    assert [(s.data, s.escala.codigo) for s in sessoes] == [(TERCA, "1-ter"), (TERCA, "2-ter"), (TERCA, "3-ter")]
    semana = sessoes_entre(ESCALAS, DOMINGO, DOMINGO + timedelta(days=6), implantacao=DOMINGO)
    assert len(semana) == 18 and semana == sorted(semana, key=lambda s: s.ordem)


def test_limites_da_competencia() -> None:
    assert limites_da_competencia("2026-02") == (date(2026, 2, 1), date(2026, 2, 28))
    assert limites_da_competencia("2026-12") == (date(2026, 12, 1), date(2026, 12, 31))
    assert Sessao(SEGUNDA, ESCALAS[0]).competencia == "2026-10"
