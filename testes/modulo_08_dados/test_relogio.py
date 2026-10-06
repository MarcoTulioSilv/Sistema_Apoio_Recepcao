from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import pytest

from sar.modulo_08_dados.relogio import RelogioSistema
from testes.apoio.relogio_controlado import RelogioControlado


class RelogioParado(RelogioSistema):
    def __init__(self, instante: datetime) -> None:
        self._instante = instante

    def agora(self) -> datetime:
        return self._instante


@pytest.mark.requisito("DDS-3.7")
def test_agora_e_em_utc() -> None:
    assert RelogioSistema().agora().utcoffset() == timedelta(0)


@pytest.mark.requisito("DDS-3.7")
@pytest.mark.parametrize(
    ("instante_utc", "data_local"),
    [
        (datetime(2026, 10, 7, 2, 59, tzinfo=UTC), date(2026, 10, 6)),  # 23:59 em Jataí
        (datetime(2026, 10, 7, 3, 0, tzinfo=UTC), date(2026, 10, 7)),  # 00:00 em Jataí
    ],
)
def test_hoje_e_a_data_local_da_clinica(instante_utc: datetime, data_local: date) -> None:
    assert RelogioParado(instante_utc).hoje() == data_local
    assert RelogioControlado(instante_utc).hoje() == data_local


@pytest.mark.requisito("DDS-3.7")
def test_relogio_controlado_so_avanca_quando_mandado() -> None:
    relogio = RelogioControlado(datetime(2026, 9, 30, 12, 0, tzinfo=UTC))
    assert relogio.agora() == relogio.agora()
    relogio.avancar(timedelta(hours=13))
    assert relogio.agora() == datetime(2026, 10, 1, 1, 0, tzinfo=UTC)
    assert relogio.hoje() == date(2026, 9, 30)
    with pytest.raises(ValueError):
        relogio.ajustar(datetime(2026, 9, 30, 12, 0))  # noqa: DTZ001 — o teste é justamente o instante sem fuso
