"""Verificação da cadeia como função pura (CT-AUD-03, QAS-13): cada tipo de adulteração é apontado."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from sar.modulo_01_acesso.regras import cinco_anos_antes, json_do_elo, verificar_elos
from sar.modulo_08_dados.canonico import HASH_INICIAL, calcular_hash
from sar.modulo_08_dados.interfaces.trilha import Ancora, Cabeca, Elo

INICIO = datetime(2026, 9, 1, 12, 0, tzinfo=UTC)


def cadeia(n: int, primeiro: int = 1, inicial: str = HASH_INICIAL) -> list[Elo]:
    elos, anterior = [], inicial
    for i in range(primeiro, primeiro + n):
        elo = Elo(i, INICIO + timedelta(hours=i), 7, None, "teste.op", "teste", str(i), None, None, "web", None,
                  "a" * 32, 1, anterior, "")  # fmt: skip
        elo = replace(elo, hash_registro=calcular_hash(anterior, json_do_elo(elo)))
        elos.append(elo)
        anterior = elo.hash_registro
    return elos


def recalcular(elos: list[Elo], a_partir: int) -> list[Elo]:
    """Refaz os hashes a partir de uma posição, como faria quem quisesse esconder a alteração."""
    saida = elos[:a_partir]
    anterior = saida[-1].hash_registro if saida else HASH_INICIAL
    for elo in elos[a_partir:]:
        elo = replace(elo, hash_anterior=anterior)
        elo = replace(elo, hash_registro=calcular_hash(anterior, json_do_elo(elo)))
        saida.append(elo)
        anterior = elo.hash_registro
    return saida


def verificar(elos: list[Elo], cabeca: Cabeca | None = None, ancoras: list[Ancora] | None = None, **kw: object):  # type: ignore[no-untyped-def]
    cabeca = cabeca or Cabeca(elos[-1].id, elos[-1].hash_registro)
    primeiro = kw.pop("primeiro_id", 1)
    inicial = kw.pop("hash_inicial", HASH_INICIAL)
    return verificar_elos(elos, primeiro_id=primeiro, hash_inicial=inicial, cabeca=cabeca, ancoras=ancoras or [])  # type: ignore[arg-type]


@pytest.mark.requisito("RNF-615", "CT-AUD-03")
def test_cadeia_integra() -> None:
    resultado = verificar(cadeia(10))
    assert (resultado.integra, resultado.verificados, resultado.primeiro_divergente_id) == (True, 10, None)


@pytest.mark.requisito("RNF-615", "CT-AUD-03", "QAS-13")
def test_registro_alterado_e_apontado() -> None:
    elos = cadeia(10)
    elos[4] = replace(elos[4], motivo="adulterado")
    resultado = verificar(elos)
    assert (resultado.integra, resultado.primeiro_divergente_id, resultado.motivo) == (False, 5, "hash")
    assert resultado.verificados == 4
    assert resultado.alterado_depois_de == elos[4].instante  # sem âncora: depois de o registro existir


@pytest.mark.requisito("RNF-615", "CT-AUD-03")
def test_alteracao_com_hash_recalculado_quebra_o_elo_seguinte() -> None:
    elos = cadeia(10)
    elos[4] = replace(elos[4], motivo="adulterado")
    elos[4] = replace(elos[4], hash_registro=calcular_hash(elos[4].hash_anterior, json_do_elo(elos[4])))
    assert (verificar(elos).primeiro_divergente_id, verificar(elos).motivo) == (6, "elo")


@pytest.mark.requisito("RNF-615", "CT-AUD-03", "QAS-13")
def test_reescrita_completa_e_pega_pela_ancora() -> None:
    originais = cadeia(10)
    ancora = Ancora(1, 8, originais[7].hash_registro, INICIO + timedelta(days=2), None, None)
    adulterados = list(originais)
    adulterados[4] = replace(adulterados[4], motivo="adulterado")
    adulterados = recalcular(adulterados, 4)
    resultado = verificar(adulterados, ancoras=[ancora])  # a cabeça também foi reescrita
    assert (resultado.primeiro_divergente_id, resultado.motivo) == (8, "ancora")
    assert resultado.alterado_depois_de == ancora.registrada_em  # QAS-13: data aproximada


@pytest.mark.requisito("RNF-615", "CT-AUD-03")
def test_registro_apagado_no_meio_e_apontado() -> None:
    elos = cadeia(10)
    del elos[3]
    resultado = verificar(elos)
    assert (resultado.primeiro_divergente_id, resultado.motivo) == (4, "sequencia")


@pytest.mark.requisito("RNF-615", "CT-AUD-03")
def test_registros_apagados_no_fim_sao_pegos_pela_cabeca() -> None:
    elos = cadeia(10)
    cabeca = Cabeca(10, elos[-1].hash_registro)
    resultado = verificar(elos[:8], cabeca=cabeca)
    assert (resultado.primeiro_divergente_id, resultado.motivo) == (9, "cabeca")


@pytest.mark.requisito("RNF-628", "CT-AUD-05")
def test_verificacao_recomeca_do_ponto_de_corte() -> None:
    completa = cadeia(10)
    restante = completa[6:]  # 1 a 6 expurgados; o corte guarda o hash do 6
    resultado = verificar(restante, primeiro_id=7, hash_inicial=completa[5].hash_registro)
    assert (resultado.integra, resultado.verificados) == (True, 4)
    assert not verificar(restante, primeiro_id=7, hash_inicial=HASH_INICIAL).integra


@pytest.mark.requisito("RNF-615")
def test_cadeia_vazia_e_integra() -> None:
    assert verificar([], cabeca=Cabeca(0, HASH_INICIAL)).integra


@pytest.mark.requisito("RNF-628")
@pytest.mark.parametrize(
    ("instante", "limite"),
    [
        (datetime(2026, 10, 6, 2, 50, tzinfo=UTC), datetime(2021, 10, 6, 2, 50, tzinfo=UTC)),
        (datetime(2028, 2, 29, 2, 50, tzinfo=UTC), datetime(2023, 2, 28, 2, 50, tzinfo=UTC)),
    ],
)
def test_limite_de_cinco_anos(instante: datetime, limite: datetime) -> None:
    assert cinco_anos_antes(instante) == limite
