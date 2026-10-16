"""Casos da `CompensacaoEngine` e do balanço (DDS §7.4 e §7.5): CT-FRQ-05, 07, 08 e 09.

Outubro de 2026 começa numa quinta: a escala 1-seg tem 13 vagas (5 sextas, 4 segundas, 4 quartas) e a 1-ter,
14 (5 quintas, 5 sábados, 4 terças).
"""

from __future__ import annotations

from collections.abc import Iterable, Set
from datetime import date

import pytest

from sar.modulo_03_operacao.calendario import Sessao
from sar.modulo_03_operacao.compensacao import (
    Classificacao,
    Ligacao,
    Marcacao,
    Periodo,
    Troca,
    Vigencia,
    compensar,
    vagas_previstas,
)
from sar.modulo_03_operacao.contrato import OrigemPar
from testes.apoio.operacao import POR_CODIGO

OUT = "2026-10"
SEG, TER = POR_CODIGO["1-seg"], POR_CODIGO["1-ter"]
IMPLANTADO = date(2026, 1, 1)


def dia(n: int, mes: int = 10) -> date:
    return date(2026, mes, n)


def s(n: int, escala: str = "1-seg", mes: int = 10) -> Sessao:
    return Sessao(dia(n, mes), POR_CODIGO[escala])


def periodo(inicio: date, fim: date | None = None, *vigencias: Vigencia) -> Periodo:
    return Periodo(inicio, fim, vigencias or (Vigencia(inicio, SEG),))


def marcar(vagas: list[Sessao], ausentes: Set[int] = frozenset(), fora: Iterable[Sessao] = ()) -> list[Marcacao]:
    """As vagas, presentes salvo as dos dias em `ausentes`, mais as presenças fora da escala."""
    return [*(Marcacao(v, v.data.day not in ausentes) for v in vagas), *(Marcacao(f, True) for f in fora)]


def numeros(sessoes: Iterable[Sessao]) -> list[int]:
    return [x.data.day for x in sessoes]


# ------------------------------------------------------------------ vagas previstas
@pytest.mark.requisito("CT-FRQ-07", "RNF-101", "P-09")
@pytest.mark.parametrize(
    ("periodos", "implantacao", "esperadas"),
    [
        ([periodo(dia(1, 1))], IMPLANTADO, 13),  # outubro: 5 sextas, 4 segundas e 4 quartas
        ([Periodo(dia(1, 1), None, (Vigencia(dia(1, 1), TER),))], IMPLANTADO, 14),
        ([periodo(dia(14))], IMPLANTADO, 8),  # início no meio do mês, numa quarta
        ([periodo(dia(1, 1), dia(21))], IMPLANTADO, 9),  # o dia do evento (quarta, 21) conta
        ([periodo(dia(1, 1), None, Vigencia(dia(1, 1), SEG), Vigencia(dia(16), TER))], IMPLANTADO, 6 + 7),
        ([periodo(dia(1, 1), None, Vigencia(dia(1, 1), SEG), Vigencia(dia(19), None))], IMPLANTADO, 7),  # DD-27
        ([periodo(dia(1, 1))], dia(10), 9),  # RN-05: só a partir da implantação
        ([periodo(dia(1, 1), dia(9)), Periodo(dia(20), None, (Vigencia(dia(20), TER),))], IMPLANTADO, 4 + 6),
        ([periodo(dia(1, 1))], None, 0),  # DD-91
    ],
)
def test_vagas_previstas_pela_vigencia_e_pelo_periodo(
    periodos: list[Periodo], implantacao: date | None, esperadas: int
) -> None:
    assert len(vagas_previstas(OUT, periodos, implantacao)) == esperadas


@pytest.mark.requisito("CT-FRQ-07", "RNF-101")
def test_fevereiro_com_quatro_ocorrencias_de_cada_dia() -> None:
    vagas = vagas_previstas("2026-02", [periodo(dia(1, 1))], IMPLANTADO)
    assert numeros(vagas) == [2, 4, 6, 9, 11, 13, 16, 18, 20, 23, 25, 27]


# ------------------------------------------------------------------ pareamento
@pytest.mark.requisito("CT-FRQ-05", "RF-918")
def test_ausencia_mais_antiga_com_presenca_mais_antiga_no_mesmo_mes() -> None:
    vagas = vagas_previstas(OUT, [periodo(dia(1, 1))], IMPLANTADO)
    setembro = s(29, "1-ter", mes=9)  # não compensa outubro
    marcacoes = marcar(vagas, ausentes={12, 5}, fora=[s(13, "1-ter"), s(8, "1-ter"), setembro])
    resultado = compensar(OUT, vagas, marcacoes)
    assert [(p.ausencia.data.day, p.presenca.data.day, p.origem) for p in resultado.pares] == [
        (5, 8, OrigemPar.AUTOMATICO),
        (12, 13, OrigemPar.AUTOMATICO),
    ]
    assert resultado.classificacao(s(8, "1-ter")) is Classificacao.REPOSICAO
    balanco = resultado.balanco(mes_fechado=True)
    assert (balanco.previstas, balanco.realizadas, balanco.reposicoes, balanco.extras) == (13, 13, 2, 0)
    assert balanco.ausencias_nao_compensadas == 0 and not balanco.provisorio


@pytest.mark.requisito("P-10", "RF-918")
def test_troca_pontual_tem_prioridade_e_deixa_de_compensar_se_o_paciente_veio() -> None:
    vagas = vagas_previstas(OUT, [periodo(dia(1, 1))], IMPLANTADO)
    troca = Troca(dia(7), s(15, "1-ter"))
    marcacoes = marcar(vagas, ausentes={5, 7}, fora=[s(8, "1-ter"), s(15, "1-ter")])
    resultado = compensar(OUT, vagas, marcacoes, trocas=[troca])
    assert [(p.ausencia.data.day, p.presenca.data.day, p.origem) for p in resultado.pares] == [
        (5, 8, OrigemPar.AUTOMATICO),
        (7, 15, OrigemPar.TROCA),
    ]
    assert resultado.classificacao(s(15, "1-ter")) is Classificacao.TROCA

    veio_mesmo_assim = compensar(OUT, vagas, marcar(vagas, fora=[s(15, "1-ter")]), [troca])
    assert veio_mesmo_assim.pares == () and numeros(veio_mesmo_assim.extras) == [15]


@pytest.mark.requisito("DD-25", "RF-918")
def test_ligacao_manual_vale_antes_do_automatico_e_a_invalida_e_ignorada() -> None:
    vagas = vagas_previstas(OUT, [periodo(dia(1, 1))], IMPLANTADO)
    marcacoes = marcar(vagas, ausentes={5, 12}, fora=[s(8, "1-ter"), s(13, "1-ter")])
    manual = Ligacao(s(5), s(13, "1-ter"))
    invalida = Ligacao(s(7), s(8, "1-ter"))  # a quarta, 7, foi presença: a ligação deixou de valer
    resultado = compensar(OUT, vagas, marcacoes, ligacoes=[invalida, manual])
    assert [(p.ausencia.data.day, p.presenca.data.day, p.origem) for p in resultado.pares] == [
        (5, 13, OrigemPar.MANUAL),
        (12, 8, OrigemPar.AUTOMATICO),
    ]
    assert resultado.ligacoes_ignoradas == (invalida,)


@pytest.mark.requisito("RF-916")
def test_mes_aberto_tem_vagas_a_realizar_e_extras_provisorias() -> None:
    vagas = vagas_previstas(OUT, [periodo(dia(1, 1))], IMPLANTADO)
    ate_dia_16 = marcar([v for v in vagas if v.data.day <= 16], fora=[s(10, "1-ter")])
    balanco = compensar(OUT, vagas, ate_dia_16).balanco(mes_fechado=False)
    assert (balanco.previstas, balanco.realizadas, balanco.a_realizar, balanco.extras) == (13, 8, 6, 1)
    assert balanco.provisorio


# ------------------------------------------------------------------ extras e sessões não realizadas
@pytest.mark.requisito("CT-FRQ-08", "RN-01", "INV-05", "RF-506")
@pytest.mark.parametrize(("extras", "aviso", "pendencia"), [(3, False, False), (4, True, False), (5, True, True)])
def test_aviso_com_quatro_extras_e_pendencia_a_partir_da_quinta(extras: int, aviso: bool, pendencia: bool) -> None:
    vagas = vagas_previstas(OUT, [periodo(dia(1, 1))], IMPLANTADO)
    fora = [s(n, "1-ter") for n in (1, 3, 6, 8, 10)[:extras]]
    balanco = compensar(OUT, vagas, marcar(vagas, fora=fora)).balanco(mes_fechado=False)
    assert (balanco.extras, balanco.aviso_extra, balanco.extra_alem_do_limite) == (extras, aviso, pendencia)


@pytest.mark.requisito("CT-FRQ-09", "DEC-66", "P-12")
def test_sessao_nao_realizada_sai_das_previstas_e_nao_gera_ausencia() -> None:
    vagas = vagas_previstas(OUT, [periodo(dia(1, 1))], IMPLANTADO, nao_realizadas=[(dia(5), SEG.id)])
    assert len(vagas) == 12 and s(5) not in vagas
    resultado = compensar(OUT, vagas, marcar(vagas))
    assert resultado.ausencias == () and resultado.balanco(mes_fechado=True).previstas == 12
