from __future__ import annotations

import pytest

from sar.web.configuracao import ConfigWeb


@pytest.mark.requisito("DD-80", "DD-84")
@pytest.mark.parametrize(
    "origem", ["https://sar.clinica.local", "https://192.168.0.150:8443", "https://sar.clinica.local/"]
)
def test_origem_https_vale_em_producao(origem: str) -> None:
    assert ConfigWeb(origem=origem).origem_normalizada == origem.rstrip("/")


@pytest.mark.requisito("DD-80", "DD-84")
@pytest.mark.parametrize("origem", ["http://sar.clinica.local", "sar.clinica.local", "https://sar/entrar", "ftp://sar"])
def test_origem_invalida_ou_sem_https_em_producao_e_recusada(origem: str) -> None:
    with pytest.raises(ValueError):
        ConfigWeb(origem=origem)


@pytest.mark.requisito("DD-85")
def test_superusuario_fora_do_desenvolvimento_impede_a_subida() -> None:
    with pytest.raises(ValueError):
        ConfigWeb(origem="https://sar.clinica.local", superusuarios=frozenset({1}))
    assert ConfigWeb(origem="http://127.0.0.1:8080", desenvolvimento=True, superusuarios=frozenset({1})).superusuarios
