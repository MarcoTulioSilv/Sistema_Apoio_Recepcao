"""Os modelos ORM batem com o esquema que as migrações criam (AD-10: nenhuma divergência entre código e
banco). Só as tabelas que já têm modelo entram na comparação, e só as chaves estrangeiras cujo alvo também tem."""

from __future__ import annotations

import pytest
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import Engine

import sar.modulo_08_dados.modelos.acesso
import sar.modulo_08_dados.modelos.cadastro
import sar.modulo_08_dados.modelos.configuracao  # noqa: F401 — registra os modelos no metadata
from sar.modulo_08_dados.modelos import Base

pytestmark = pytest.mark.integracao


def _so_tabelas_com_modelo(objeto: object, nome: str | None, tipo: str, refletido: bool, comparado: object) -> bool:
    if tipo == "table":
        return nome in Base.metadata.tables
    if tipo == "foreign_key_constraint":  # periodo_tratamento → documento, cujo modelo vem no Incremento 4
        alvo = getattr(getattr(objeto, "referred_table", None), "name", None)
        if alvo is not None and alvo not in Base.metadata.tables:
            return False
    tabela = getattr(objeto, "table", None)
    return tabela is None or tabela.name in Base.metadata.tables


@pytest.mark.requisito("AD-10", "DD-12")
def test_modelos_iguais_ao_banco_migrado(engine_migracao: Engine) -> None:
    with engine_migracao.connect() as conexao:
        contexto = MigrationContext.configure(
            conexao, opts={"compare_type": True, "include_object": _so_tabelas_com_modelo}
        )
        diferencas = compare_metadata(contexto, Base.metadata)
    assert diferencas == []
