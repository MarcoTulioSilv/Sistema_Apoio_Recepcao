from __future__ import annotations

from datetime import date

import pytest

from sar.modulo_06_configuracao.regras import de_texto, para_texto, validar
from sar.nucleo.erros import RegraViolada
from sar.nucleo.parametros import PARAMETROS, Unidade

INATIVIDADE = PARAMETROS["sessao_inatividade"]  # 2 a 30 min
EXTRACAO = PARAMETROS["extracao_ligada"]
IMPLANTACAO = PARAMETROS["data_implantacao"]


@pytest.mark.requisito("DD-48")
@pytest.mark.parametrize("valor", [2, 10, 30])
def test_aceita_valor_nos_limites(valor: int) -> None:
    assert validar(INATIVIDADE, valor) == valor


@pytest.mark.requisito("DD-48")
@pytest.mark.parametrize("valor", [0, 1, 31, -5])
def test_recusa_valor_fora_dos_limites_com_os_limites_no_detalhe(valor: int) -> None:
    with pytest.raises(RegraViolada) as erro:
        validar(INATIVIDADE, valor)
    assert erro.value.codigo == "parametro.fora_dos_limites"
    assert (erro.value.detalhe["minimo"], erro.value.detalhe["maximo"]) == (2, 30)


@pytest.mark.requisito("DD-48")
@pytest.mark.parametrize(
    ("parametro", "valor"),
    [(INATIVIDADE, True), (INATIVIDADE, "10"), (EXTRACAO, 1), (IMPLANTACAO, "2026-10-01")],
    ids=["bool-como-int", "texto-como-int", "int-como-bool", "texto-como-data"],
)
def test_recusa_valor_de_outro_tipo(parametro: object, valor: object) -> None:
    with pytest.raises(RegraViolada) as erro:
        validar(parametro, valor)  # type: ignore[arg-type]
    assert erro.value.codigo == "parametro.tipo"


@pytest.mark.requisito("DD-48")
@pytest.mark.parametrize("nome", sorted(n for n, p in PARAMETROS.items() if p.padrao is not None))
def test_padrao_vai_e_volta_pelo_texto_gravado(nome: str) -> None:
    parametro = PARAMETROS[nome]
    assert de_texto(parametro, para_texto(parametro, parametro.padrao)) == parametro.padrao


@pytest.mark.requisito("DD-48")
def test_data_e_booleano_no_texto_gravado() -> None:
    assert para_texto(IMPLANTACAO, date(2026, 11, 3)) == "2026-11-03"
    assert de_texto(IMPLANTACAO, "2026-11-03") == date(2026, 11, 3)
    assert (para_texto(EXTRACAO, False), de_texto(EXTRACAO, "false")) == ("false", False)
    assert EXTRACAO.unidade is Unidade.BOOLEANO


@pytest.mark.requisito("DD-48")
@pytest.mark.parametrize(("parametro", "texto"), [(INATIVIDADE, "dez"), (EXTRACAO, "sim"), (INATIVIDADE, "99")])
def test_texto_gravado_invalido_e_recusado(parametro: object, texto: str) -> None:
    with pytest.raises((ValueError, RegraViolada)):
        de_texto(parametro, texto)  # type: ignore[arg-type]
