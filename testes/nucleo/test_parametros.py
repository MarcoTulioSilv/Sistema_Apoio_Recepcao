from __future__ import annotations

from datetime import date

import pytest

from sar.nucleo.contexto import Perfil
from sar.nucleo.parametros import PARAMETROS, Unidade


@pytest.mark.requisito("DD-48", "DD-73")
@pytest.mark.parametrize("nome", sorted(PARAMETROS))
def test_declaracao_do_parametro_e_coerente(nome: str) -> None:
    p = PARAMETROS[nome]
    assert p.nome == nome
    assert p.editor in (Perfil.ADMINISTRACAO, Perfil.TI)
    if p.unidade is Unidade.BOOLEANO:
        assert isinstance(p.padrao, bool)
        assert p.minimo is None and p.maximo is None
    elif p.unidade is Unidade.DATA:
        assert p.padrao is None or isinstance(p.padrao, date)
    else:
        assert isinstance(p.padrao, int) and not isinstance(p.padrao, bool)
        assert p.minimo is not None and p.maximo is not None
        assert p.minimo <= p.padrao <= p.maximo
