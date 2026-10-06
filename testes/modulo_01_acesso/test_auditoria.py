from __future__ import annotations

from datetime import UTC, datetime
from typing import cast

import pytest

from sar.modulo_01_acesso.servicos import ServicoAuditoria
from sar.nucleo.contexto import Contexto, Perfil
from sar.nucleo.uow import RegistroAuditoria, UnidadeDeTrabalho

CONTEXTO = Contexto(7, Perfil.RECEPCAO, 3, "10.0.0.5", datetime(2026, 9, 30, 12, 0, tzinfo=UTC), "a" * 32)


class UowFalsa:
    def __init__(self) -> None:
        self.registros: list[RegistroAuditoria] = []

    def auditar(self, registro: RegistroAuditoria) -> None:
        self.registros.append(registro)


def registrar(**kwargs: object) -> list[RegistroAuditoria]:
    uow = UowFalsa()
    argumentos: dict[str, object] = {
        "operacao": "cadastro.paciente.atualizar",
        "entidade": "paciente",
        "entidade_id": "42",
    }
    argumentos.update(kwargs)
    ServicoAuditoria().registrar(cast(UnidadeDeTrabalho, uow), CONTEXTO, **argumentos)  # type: ignore[arg-type]
    return uow.registros


@pytest.mark.requisito("DD-10", "RNF-605")
def test_registra_so_os_campos_que_mudaram() -> None:
    [registro] = registrar(alteracoes={"nome": ("A", "B"), "cpf": ("1", "1")}, motivo="correção")
    assert registro.alteracoes == {"nome": ("A", "B")}
    assert (registro.contexto, registro.motivo, registro.autorizador_id) == (CONTEXTO, "correção", None)


@pytest.mark.requisito("DD-10")
def test_sem_mudanca_real_registra_sem_alteracoes() -> None:
    [registro] = registrar(alteracoes={"nome": ("A", "A")})
    assert registro.alteracoes is None


@pytest.mark.requisito("DD-03", "DDS-3.10")
def test_valor_sem_forma_canonica_e_recusado_na_hora_e_nada_e_registrado() -> None:
    uow = UowFalsa()
    with pytest.raises(TypeError):
        ServicoAuditoria().registrar(
            cast(UnidadeDeTrabalho, uow), CONTEXTO, "x.y", "paciente", "1", {"foto": (None, b"\x89PNG")}
        )
    assert uow.registros == []


@pytest.mark.requisito("DD-03")
@pytest.mark.parametrize(
    "kwargs",
    [
        {"operacao": "x" * 81},
        {"entidade": "x" * 61},
        {"entidade_id": "x" * 41},
        {"motivo": "x" * 501},
        {"operacao": ""},
    ],
)
def test_recusa_campo_fora_do_tamanho_da_coluna(kwargs: dict[str, object]) -> None:
    with pytest.raises(ValueError):
        registrar(**kwargs)
