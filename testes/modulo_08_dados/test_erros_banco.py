from __future__ import annotations

import pytest
from sqlalchemy.exc import IntegrityError, OperationalError

from sar.modulo_08_dados.erros_banco import anotar_restricao, restricao_violada
from sar.nucleo.logs import ATRIBUTO_RESTRICAO


class ErroDriver(Exception):
    pass


def erro(codigo: int, mensagem: str) -> IntegrityError:
    return IntegrityError("INSERT ...", {}, ErroDriver(codigo, mensagem))


@pytest.mark.requisito("DD-81", "CT-LOG-02")
@pytest.mark.parametrize(
    ("codigo", "mensagem", "restricao"),
    [
        (1062, "Duplicate entry '52998224725' for key 'paciente.uq_paciente__cpf'", "uq_paciente__cpf"),
        (3819, "Check constraint 'ck_paciente__cpf' is violated.", "ck_paciente__cpf"),
        (
            1452,
            "Cannot add or update a child row: a foreign key constraint fails (`sar`.`contato`, CONSTRAINT "
            "`fk_contato__paciente_id` FOREIGN KEY (`paciente_id`) REFERENCES `paciente` (`id`))",
            "fk_contato__paciente_id",
        ),
        (1048, "Column 'nome' cannot be null", None),
    ],
)
def test_extrai_so_o_nome_da_restricao(codigo: int, mensagem: str, restricao: str | None) -> None:
    assert restricao_violada(erro(codigo, mensagem)) == restricao


@pytest.mark.requisito("DD-81")
def test_erro_sem_codigo_do_mysql_nao_tem_restricao() -> None:
    assert restricao_violada(OperationalError("x", {}, ErroDriver("texto"))) is None


@pytest.mark.requisito("DD-81", "CT-LOG-02")
def test_anota_a_restricao_na_excecao() -> None:
    e = erro(1062, "Duplicate entry 'x' for key 'paciente.uq_paciente__cpf'")
    anotar_restricao(e)
    assert getattr(e, ATRIBUTO_RESTRICAO) == "uq_paciente__cpf"
