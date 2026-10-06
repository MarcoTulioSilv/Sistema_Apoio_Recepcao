from __future__ import annotations

import re

import pytest

from testes.apoio.fabrica import MARCA, Fabrica, municipios_go


def cpf_valido(cpf: str) -> bool:
    """Verificação independente da geração: recalcula os dois dígitos."""
    if not re.fullmatch(r"\d{11}", cpf) or len(set(cpf)) == 1:
        return False
    for tamanho in (9, 10):
        soma = sum(int(d) * p for d, p in zip(cpf[:tamanho], range(tamanho + 1, 1, -1), strict=True))
        if (soma * 10 % 11) % 10 != int(cpf[tamanho]):
            return False
    return True


def cns_valido(cns: str) -> bool:
    return bool(re.fullmatch(r"[12789]\d{14}", cns)) and sum(int(d) * (15 - i) for i, d in enumerate(cns)) % 11 == 0


@pytest.mark.requisito("PT-5.1")
def test_cpf_e_cns_gerados_sao_validos(fabrica: Fabrica) -> None:
    for _ in range(500):
        assert cpf_valido(fabrica.cpf())
        assert cns_valido(fabrica.cns())


@pytest.mark.requisito("PT-5.1")
def test_verificadores_recusam_documento_alterado() -> None:
    assert cpf_valido("52998224725")
    assert not cpf_valido("52998224726")
    assert not cpf_valido("11111111111")
    assert cns_valido("100000000000007")
    assert not cns_valido("100000000000008")


@pytest.mark.requisito("PT-5.1")
def test_paciente_ficticio_tem_marca_e_municipio_de_goias(fabrica: Fabrica) -> None:
    paciente = fabrica.paciente()
    assert paciente.nome.endswith(MARCA)
    assert paciente.nome_mae.endswith(MARCA)
    assert paciente.municipio.uf == "GO"
    assert re.fullmatch(r"\d{7}", paciente.municipio.codigo_ibge)


@pytest.mark.requisito("PT-5.1")
def test_mesma_semente_gera_os_mesmos_dados() -> None:
    assert Fabrica(42).paciente() == Fabrica(42).paciente()
    assert Fabrica(42).paciente() != Fabrica(43).paciente()


@pytest.mark.requisito("RF-1205")
def test_tabela_do_ibge_tem_os_municipios_de_goias() -> None:
    nomes = {m.nome for m in municipios_go()}
    assert len(nomes) == 246
    assert "Jataí" in nomes
