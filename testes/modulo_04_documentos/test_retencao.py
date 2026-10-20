"""Retenção derivada (DD-01): CT-DOC-09."""

from __future__ import annotations

from datetime import UTC, date, datetime

import pytest

from sar.modulo_04_documentos.retencao import prazo, somar_anos
from sar.nucleo.portas import MarcoRetencao

ENCERRADO = MarcoRetencao(em_tratamento=False, ultimo_encerramento=date(2026, 3, 10))


@pytest.mark.requisito("CT-DOC-09", "DD-01", "RF-709", "RNF-610")
def test_sem_prazo_em_tratamento() -> None:
    assert prazo(MarcoRetencao(True, None), datetime(2026, 1, 1, tzinfo=UTC), 20) is None
    # Voltou ao tratamento depois de encerrado: o novo período anula o prazo.
    assert prazo(MarcoRetencao(True, date(2026, 3, 10)), datetime(2026, 1, 1, tzinfo=UTC), 20) is None


@pytest.mark.requisito("CT-DOC-09", "DD-01")
def test_vinte_anos_do_ultimo_registro() -> None:
    assert prazo(ENCERRADO, datetime(2025, 5, 1, 12, tzinfo=UTC), 20) == date(2046, 3, 10)  # o evento é o último
    assert prazo(ENCERRADO, datetime(2026, 6, 1, 12, tzinfo=UTC), 20) == date(2046, 6, 1)  # o documento é o último
    # Data local da clínica: 01/06 às 01h UTC ainda é 31/05 em Jataí.
    assert prazo(ENCERRADO, datetime(2026, 6, 1, 1, tzinfo=UTC), 20) == date(2046, 5, 31)
    assert prazo(MarcoRetencao(False, None), datetime(2026, 6, 1, 12, tzinfo=UTC), 20) == date(2046, 6, 1)
    assert prazo(MarcoRetencao(False, None), None, 20) is None


def test_29_de_fevereiro() -> None:
    assert somar_anos(date(2028, 2, 29), 1) == date(2029, 2, 28)
    assert somar_anos(date(2028, 2, 29), 20) == date(2048, 2, 29)
