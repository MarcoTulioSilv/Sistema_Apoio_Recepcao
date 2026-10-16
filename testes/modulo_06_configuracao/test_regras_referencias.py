"""Regras puras dos dados de referência (DDS §10.2)."""

from __future__ import annotations

import pytest

from sar.modulo_06_configuracao.regras import termo_de_busca, validar_nome_convenio, validar_uf
from sar.nucleo.erros import RegraViolada


@pytest.mark.requisito("RF-1204")
@pytest.mark.parametrize(
    ("entrada", "esperado"),
    [("  Unimed   Goiânia ", "Unimed Goiânia"), ("SUS", "SUS"), ("Ab", "Ab"), ("x" * 100, "x" * 100)],
)
def test_nome_de_convenio_sem_espacos_sobrando(entrada: str, esperado: str) -> None:
    assert validar_nome_convenio(entrada) == esperado


@pytest.mark.requisito("RF-1204")
@pytest.mark.parametrize("entrada", ["", "   ", "A", " A ", "x" * 101])
def test_nome_de_convenio_curto_ou_longo_e_recusado(entrada: str) -> None:
    with pytest.raises(RegraViolada) as erro:
        validar_nome_convenio(entrada)
    assert erro.value.codigo == "convenio.nome"


@pytest.mark.requisito("RF-1205")
def test_uf_valida_em_maiuscula_e_inexistente_recusada() -> None:
    assert validar_uf(" go ") == "GO"
    for invalida in ("", "XX", "GOI", "G"):
        with pytest.raises(RegraViolada):
            validar_uf(invalida)


@pytest.mark.requisito("RF-1205")
def test_termo_curto_nao_busca() -> None:
    assert termo_de_busca(" j ") is None
    assert termo_de_busca("  são   luís ") == "são luís"
