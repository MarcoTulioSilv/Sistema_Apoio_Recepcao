"""Propriedades da `CompensacaoEngine` (DDS §7.6, DD-29): CT-FRQ-06, com milhares de meses gerados."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from random import Random

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from sar.modulo_03_operacao.calendario import Sessao, limites_da_competencia, sessoes_entre
from sar.modulo_03_operacao.compensacao import (
    Ligacao,
    Marcacao,
    OrigemPar,
    Periodo,
    Troca,
    Vigencia,
    compensar,
    vagas_previstas,
)
from testes.apoio.operacao import ESCALAS

IMPLANTADO = date(2025, 1, 1)


@dataclass(frozen=True)
class Mes:
    competencia: str
    previstas: list[Sessao]
    marcacoes: list[Marcacao]
    trocas: list[Troca]
    ligacoes: list[Ligacao]


@st.composite
def meses(draw: st.DrawFn) -> Mes:
    ano, mes = draw(st.sampled_from([2025, 2026, 2028])), draw(st.integers(1, 12))  # 2028: fevereiro bissexto
    comp = f"{ano}-{mes:02d}"
    primeiro, ultimo = limites_da_competencia(comp)
    dias = st.integers(0, (ultimo - primeiro).days).map(lambda n: primeiro + timedelta(days=n))
    vigencias = [Vigencia(primeiro - timedelta(days=40), draw(st.sampled_from(ESCALAS)))]
    if draw(st.booleans()):  # mudança de alocação no meio do mês, às vezes para "sem alocação"
        vigencias.append(Vigencia(draw(dias), draw(st.one_of(st.none(), st.sampled_from(ESCALAS)))))
    fim = draw(st.one_of(st.none(), dias))
    periodo = Periodo(primeiro - timedelta(days=40), fim, tuple(vigencias))
    todas = sessoes_entre(ESCALAS, primeiro, ultimo, IMPLANTADO)
    nao_realizadas = draw(st.lists(st.sampled_from(todas), max_size=3))
    previstas = vagas_previstas(comp, [periodo], IMPLANTADO, [(s.data, s.escala.id) for s in nao_realizadas])

    marcacoes = [Marcacao(v, draw(st.booleans())) for v in previstas]
    livres = [s for s in todas if s not in set(previstas)]
    fora = draw(st.lists(st.sampled_from(livres), max_size=10, unique=True)) if livres else []
    marcacoes += [Marcacao(f, True) for f in fora]
    vizinho = sessoes_entre(ESCALAS, ultimo + timedelta(days=1), ultimo + timedelta(days=7), IMPLANTADO)
    marcacoes += [Marcacao(v, True) for v in draw(st.lists(st.sampled_from(vizinho), max_size=2, unique=True))]

    qualquer = st.sampled_from(todas)
    trocas = draw(st.lists(st.builds(Troca, dias, qualquer), max_size=3, unique_by=lambda t: t.origem))
    lados = (lambda li: li.ausencia, lambda li: li.presenca)  # cada lado em no máximo uma ligação (§7.9)
    ligacoes = draw(st.lists(st.builds(Ligacao, qualquer, qualquer), max_size=4, unique_by=lados))
    return Mes(comp, previstas, marcacoes, trocas, ligacoes)


@pytest.mark.requisito("CT-FRQ-06", "DD-29", "RNF-101")
@settings(max_examples=2000, deadline=None)
@given(meses(), st.randoms(use_true_random=False))
def test_propriedades_da_engine(mes: Mes, aleatorio: Random) -> None:
    resultado = compensar(mes.competencia, mes.previstas, mes.marcacoes, mes.trocas, mes.ligacoes)
    ausencias = [p.ausencia for p in resultado.pares]
    presencas = [p.presenca for p in resultado.pares]

    # Cada ausência e cada presença participa de no máximo um par.
    assert len(set(ausencias)) == len(ausencias) and len(set(presencas)) == len(presencas)
    # Todo par liga ausência e presença do mesmo paciente e do mesmo mês (a engine é por paciente).
    assert all(p.ausencia.competencia == p.presenca.competencia == mes.competencia for p in resultado.pares)
    assert set(ausencias) <= set(resultado.ausencias) and set(presencas) <= set(resultado.fora_da_escala)
    # Pares automáticos = o menor entre ausências livres e presenças livres, depois de trocas e ligações.
    escolhidos = sum(p.origem is not OrigemPar.AUTOMATICO for p in resultado.pares)
    automaticos = sum(p.origem is OrigemPar.AUTOMATICO for p in resultado.pares)
    assert automaticos == min(len(resultado.ausencias), len(resultado.fora_da_escala)) - escolhidos
    # Previstas = regulares + ausências (todas as vagas do mês gerado têm marcação).
    assert len(resultado.previstas) == len(resultado.regulares) + len(resultado.ausencias)
    assert resultado.a_realizar == ()

    # A saída não depende da ordem das entradas.
    previstas, marcacoes, trocas, ligacoes = (list(mes.previstas), list(mes.marcacoes), list(mes.trocas),
                                              list(mes.ligacoes))  # fmt: skip
    for lista in (previstas, marcacoes, trocas, ligacoes):
        aleatorio.shuffle(lista)
    outro = compensar(mes.competencia, previstas, marcacoes, trocas, ligacoes)
    assert outro == resultado
    sessoes = resultado.previstas + resultado.fora_da_escala
    assert all(outro.classificacao(s) is resultado.classificacao(s) for s in sessoes)
