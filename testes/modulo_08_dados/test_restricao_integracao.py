"""CT-LOG-02 (PT §4.8): CPF repetido no banco gera erro com o nome da restrição, e o log não traz o valor."""

from __future__ import annotations

import logging
from collections.abc import Callable, Iterator, Sequence
from datetime import UTC, datetime
from typing import cast

import pytest
from sqlalchemy import Engine, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from sar.modulo_08_dados.uow import ExecutorSQL, UnidadeDeTrabalhoSQL
from sar.nucleo.eventos import Barramento
from sar.nucleo.logs import ATRIBUTO_RESTRICAO, campos_do_erro
from sar.nucleo.uow import RegistroAuditoria, UnidadeDeTrabalho
from testes.apoio.fabrica import Fabrica
from testes.apoio.vazamento import ColetorLogs

pytestmark = pytest.mark.integracao


def sem_auditoria(_sessao: Session, _registros: Sequence[RegistroAuditoria]) -> None:
    pass


@pytest.fixture
def prontuarios(engine_migracao: Engine) -> Iterator[list[str]]:
    criados: list[str] = []
    yield criados
    with engine_migracao.begin() as c:
        for prontuario in criados:
            c.execute(text("DELETE FROM paciente WHERE prontuario = :p"), {"p": prontuario})


@pytest.mark.requisito("RNF-624", "CT-LOG-02", "DD-81")
def test_cpf_repetido_loga_a_restricao_sem_o_valor(
    engine_migracao: Engine, fabrica: Fabrica, prontuarios: list[str]
) -> None:
    executar = ExecutorSQL(lambda: UnidadeDeTrabalhoSQL(engine_migracao, Barramento(), sem_auditoria, {}))
    cpf = fabrica.cpf()

    def inserir() -> Callable[[UnidadeDeTrabalho], None]:
        prontuario, nome = fabrica.prontuario(), fabrica.nome()
        prontuarios.append(prontuario)

        def operacao(uow: UnidadeDeTrabalho) -> None:
            cast(UnidadeDeTrabalhoSQL, uow).sessao.execute(
                text("INSERT INTO paciente (prontuario, nome, cpf, criado_em) VALUES (:p, :n, :c, :t)"),
                {"p": prontuario, "n": nome, "c": cpf, "t": datetime.now(UTC).replace(tzinfo=None)},
            )

        return operacao

    executar(inserir())
    with pytest.raises(IntegrityError) as erro:
        executar(inserir())

    assert getattr(erro.value, ATRIBUTO_RESTRICAO) == "uq_paciente__cpf"
    assert cpf not in str(erro.value).split("[SQL:")[1]  # hide_parameters: os valores não entram no texto
    coletor = ColetorLogs()
    logging.getLogger("sar.teste").addHandler(coletor)
    try:
        logging.getLogger("sar.teste").error("teste.gravacao.falhou", extra=campos_do_erro(erro.value))
    finally:
        logging.getLogger("sar.teste").removeHandler(coletor)
    assert '"restricao":"uq_paciente__cpf"' in coletor.linhas[0]
    assert cpf not in coletor.linhas[0]
