"""Regras puras do atendimento ao titular (DD-18, §11.1 linha 10)."""

from __future__ import annotations

from datetime import date

import pytest

from sar.modulo_11_titular.regras import prazo, texto_do_desfecho, urgente
from sar.nucleo.erros import RegraViolada


@pytest.mark.requisito("RF-1009", "DD-18")
def test_prazo_derivado_da_data_de_recebimento() -> None:
    assert prazo(date(2026, 10, 20), 15) == date(2026, 11, 4)
    assert prazo(date(2026, 12, 25), 15) == date(2027, 1, 9)


@pytest.mark.requisito("RF-1009")
def test_urgencia_a_tres_dias_do_prazo() -> None:
    final = date(2026, 11, 4)
    assert not urgente(final, date(2026, 10, 31))
    assert urgente(final, date(2026, 11, 1)) and urgente(final, date(2026, 11, 4)) and urgente(final, date(2026, 11, 9))


@pytest.mark.requisito("RF-1009")
def test_desfecho_sem_espacos_sobrando_e_com_tamanho_minimo() -> None:
    assert texto_do_desfecho("  Cópia   entregue  ", "x") == "Cópia entregue"
    for invalido in ("", "   curto ", "x" * 2001):
        with pytest.raises(RegraViolada) as erro:
            texto_do_desfecho(invalido, "titular.desfecho")
        assert erro.value.codigo == "titular.desfecho"
