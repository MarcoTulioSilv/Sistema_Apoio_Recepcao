"""Formatos de tela de telefone e CEP: só na tela; o banco guarda os dígitos (DDS §6.4)."""

from __future__ import annotations

import pytest

from sar.web.formatos import cep, telefone


@pytest.mark.requisito("RF-202")
@pytest.mark.parametrize(
    ("entrada", "tela"),
    [("999990001", "99999-0001"), ("36310002", "3631-0002"), ("99999-0001", "99999-0001"), ("123", "123"), (None, "")],
)
def test_telefone_celular_5_4_e_fixo_4_4(entrada: str | None, tela: str) -> None:
    assert telefone(entrada) == tela


@pytest.mark.requisito("RF-101")
@pytest.mark.parametrize(
    ("entrada", "tela"), [("75800000", "75800-000"), ("75800-000", "75800-000"), ("758", "758"), (None, "")]
)
def test_cep_5_3(entrada: str | None, tela: str) -> None:
    assert cep(entrada) == tela
