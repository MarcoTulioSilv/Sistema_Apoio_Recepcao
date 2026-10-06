from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime

import pytest

from sar.nucleo.contexto import Contexto, Perfil
from sar.nucleo.logs import encerrar_requisicao, iniciar_requisicao

AGORA = datetime(2026, 9, 30, 12, 0, tzinfo=UTC)


@pytest.fixture(autouse=True)
def sem_requisicao() -> Iterator[None]:
    encerrar_requisicao()
    yield
    encerrar_requisicao()


@pytest.mark.requisito("DD-81")
def test_contexto_de_sistema_usa_o_id_da_execucao_em_andamento() -> None:
    ident = iniciar_requisicao()
    assert Contexto.sistema("job", AGORA).requisicao_id == ident


@pytest.mark.requisito("DD-81")
def test_contexto_de_sistema_sem_execucao_ganha_id_novo() -> None:
    a, b = Contexto.sistema("job", AGORA), Contexto.sistema("job", AGORA)
    assert len(a.requisicao_id) == 32
    assert a.requisicao_id != b.requisicao_id
    assert a.e_sistema and a.usuario_id is None


@pytest.mark.requisito("DD-81", "DDS-3.2")
@pytest.mark.parametrize(
    ("requisicao_id", "instante"),
    [("x" * 32, AGORA), ("a" * 31, AGORA), ("a" * 32, datetime(2026, 9, 30, 12, 0))],  # noqa: DTZ001
)
def test_recusa_id_fora_do_formato_e_instante_sem_fuso(requisicao_id: str, instante: datetime) -> None:
    with pytest.raises(ValueError):
        Contexto(1, Perfil.RECEPCAO, 1, "10.0.0.5", instante, requisicao_id)
