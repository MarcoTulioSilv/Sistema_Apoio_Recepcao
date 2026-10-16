"""Lista esperada de uma sessão (DDS §7.2): CT-FRQ-01, P-10, INV-01, INV-04, DD-24."""

from __future__ import annotations

from datetime import date

import pytest

from sar.modulo_03_operacao.calendario import Sessao
from sar.modulo_03_operacao.compensacao import Periodo, Troca, Vigencia
from sar.modulo_03_operacao.lista_esperada import Esperado, Origem, SituacaoPaciente, lista_esperada
from testes.apoio.operacao import POR_CODIGO

SEGUNDA = date(2026, 10, 19)
SESSAO = Sessao(SEGUNDA, POR_CODIGO["1-seg"])
OUTRA = Sessao(date(2026, 10, 20), POR_CODIGO["1-ter"])
DESDE = date(2026, 1, 5)


def periodo(escala: str | None = "1-seg", inicio: date = DESDE, fim: date | None = None) -> tuple[Periodo, ...]:
    return (Periodo(inicio, fim, (Vigencia(inicio, POR_CODIGO[escala] if escala else None),)),)


@pytest.mark.requisito("CT-FRQ-01", "P-10", "INV-01", "INV-04")
@pytest.mark.parametrize(
    ("paciente", "esperado"),
    [
        (SituacaoPaciente(1, periodo()), (Origem.ALOCADO, True)),
        (SituacaoPaciente(2, periodo("1-ter")), None),  # outra escala
        (SituacaoPaciente(3, periodo(None)), None),  # sem alocação: só na pendência (RF-403)
        (SituacaoPaciente(4, periodo(fim=SEGUNDA)), (Origem.ALOCADO, True)),  # o dia do evento ainda conta
        (SituacaoPaciente(5, periodo(fim=date(2026, 10, 16))), None),  # período encerrado antes
        (SituacaoPaciente(6, periodo(inicio=date(2026, 10, 21))), None),  # período começa depois (INV-04)
        (SituacaoPaciente(7, periodo(), obito=date(2026, 10, 18)), None),  # óbito anterior (INV-01)
        (
            SituacaoPaciente(8, periodo("1-ter"), trocas=(Troca(date(2026, 10, 20), SESSAO),)),
            (Origem.TROCA_CHEGANDO, True),
        ),
        (SituacaoPaciente(9, periodo("2-seg"), extras=(SESSAO,)), (Origem.EXTRA_PLANEJADA, True)),
        (SituacaoPaciente(10, periodo(), trocas=(Troca(SEGUNDA, OUTRA),)), (Origem.TROCA_SAINDO, False)),  # P-10
        (SituacaoPaciente(11, periodo("1-ter", inicio=date(2026, 10, 20)), extras=(SESSAO,)), None),  # INV-04
        (SituacaoPaciente(12, periodo("1-ter"), extras=(OUTRA,)), None),  # extra de outra sessão
    ],
)
def test_quem_aparece_e_com_qual_marcacao(paciente: SituacaoPaciente, esperado: tuple[Origem, bool] | None) -> None:
    itens = lista_esperada(SESSAO, [paciente], excecoes={})
    assert [(i.origem, i.presente) for i in itens] == ([esperado] if esperado else [])


@pytest.mark.requisito("CT-FRQ-01", "DD-24", "P-13")
def test_excecoes_gravadas_acrescentam_e_sobrepoem_o_padrao() -> None:
    candidatos = [
        SituacaoPaciente(1, periodo()),
        SituacaoPaciente(2, periodo("1-ter")),  # acrescentado pela recepção
        SituacaoPaciente(3, periodo(), trocas=(Troca(SEGUNDA, OUTRA),)),  # troca saindo, mas veio
        SituacaoPaciente(4, periodo(), obito=date(2026, 10, 1)),  # exceção antiga não ressuscita (INV-01)
        SituacaoPaciente(5, periodo()),  # ausência avisada
    ]
    itens = lista_esperada(SESSAO, reversed(candidatos), excecoes={2: True, 3: True, 4: True, 5: False})
    assert itens == [
        Esperado(1, Origem.ALOCADO, presente=True, marcado=False),
        Esperado(2, Origem.ACRESCENTADO, presente=True, marcado=True),
        Esperado(3, Origem.TROCA_SAINDO, presente=True, marcado=True),
        Esperado(5, Origem.ALOCADO, presente=False, marcado=True),
    ]


@pytest.mark.requisito("DD-27")
def test_alocacao_que_muda_no_meio_do_mes() -> None:
    mudou = (Periodo(DESDE, None, (Vigencia(DESDE, POR_CODIGO["1-ter"]), Vigencia(SEGUNDA, POR_CODIGO["1-seg"]))),)
    assert [i.origem for i in lista_esperada(SESSAO, [SituacaoPaciente(1, mudou)], {})] == [Origem.ALOCADO]
    assert lista_esperada(OUTRA, [SituacaoPaciente(1, mudou)], {}) == []
