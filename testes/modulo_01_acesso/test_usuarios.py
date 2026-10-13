from __future__ import annotations

import pytest

from sar.modulo_01_acesso.regras import senha_provisoria, validar_login, validar_nome, validar_senha
from sar.nucleo.erros import RegraViolada


@pytest.mark.requisito("RF-1002")
@pytest.mark.parametrize(
    ("digitado", "gravado"), [("Maria.Souza", "maria.souza"), ("  ti_01 ", "ti_01"), ("ana-p", "ana-p")]
)
def test_login_normalizado(digitado: str, gravado: str) -> None:
    assert validar_login(digitado) == gravado


@pytest.mark.requisito("RF-1002")
@pytest.mark.parametrize("login", ["ab", "maria souza", "joão", ".maria", "x" * 61, "maria@clinica"])
def test_login_fora_do_formato(login: str) -> None:
    with pytest.raises(RegraViolada):
        validar_login(login)


@pytest.mark.requisito("RF-1002")
def test_nome_sem_espacos_sobrando() -> None:
    assert validar_nome("  Maria   da  Silva ") == "Maria da Silva"
    with pytest.raises(RegraViolada):
        validar_nome("   ")


@pytest.mark.requisito("DD-83")
def test_senha_provisoria_sempre_passa_na_politica() -> None:
    sorteadas = {senha_provisoria("maria.souza", "Maria Souza Fictício") for _ in range(200)}
    assert len(sorteadas) == 200
    for senha in sorteadas:
        validar_senha(senha, "maria.souza", "Maria Souza Fictício")
