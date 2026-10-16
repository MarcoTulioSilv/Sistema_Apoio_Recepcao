"""Fixtures do MOD-03: cadastro e operação vazios, com uma enfermeira entre os usuários de teste."""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from sqlalchemy import Engine, text

from testes.apoio.acesso import CriarUsuario
from testes.conftest import ZERAR_CADASTRO


@pytest.fixture
def operacao_zerada(
    cadastro_zerado: dict[str, int], criar_usuario: CriarUsuario, trilha_zerada: Engine
) -> Iterator[dict[str, int]]:
    ids = dict(cadastro_zerado)
    ids["enfermagem"] = criar_usuario("teste_enfermagem", perfil="enfermagem")
    yield ids
    with trilha_zerada.begin() as c:  # antes dos usuários, que as sessões, ciências e parâmetros referenciam
        for comando in (*ZERAR_CADASTRO, "DELETE FROM parametro"):
            c.execute(text(comando))
