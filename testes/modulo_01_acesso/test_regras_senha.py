"""Política de senha (DD-83), bloqueio progressivo (§5.2) e hash bcrypt (AD-19)."""

from __future__ import annotations

import pytest

from sar.modulo_01_acesso.regras import minutos_de_bloqueio, validar_senha
from sar.modulo_01_acesso.senhas import CUSTO, Hasher
from sar.nucleo.erros import RegraViolada

LOGIN, NOME = "marco.tulio", "Marco Túlio Fictício"


@pytest.mark.requisito("DD-83")
@pytest.mark.parametrize(
    "senha",
    ["cafe com leite", "Quintal-azul-77", "minha bicicleta", "jabuticaba", "tres patos amarelos", "Pé de moleque"],
)
def test_aceita_senha_simples_que_nao_e_muito_fraca(senha: str) -> None:
    validar_senha(senha, LOGIN, NOME)


@pytest.mark.requisito("DD-83")
@pytest.mark.parametrize(
    "senha",
    [
        "12345678",  # lista
        "senha123",  # lista
        "Brasil2024!",  # palavra comum com número no fim
        "Clínica123",  # acento não esconde
        "abcdefgh",  # sequência
        "87654321",  # sequência ao contrário
        "qwertyui",  # fileira do teclado
        "aaaaaaaa",  # repetição
        "abababab",  # repetição
        "abcabcabc",  # repetição
    ],
)
def test_recusa_senha_muito_fraca(senha: str) -> None:
    with pytest.raises(RegraViolada) as erro:
        validar_senha(senha, LOGIN, NOME)
    assert erro.value.codigo == "senha.fraca"


@pytest.mark.requisito("DD-83")
@pytest.mark.parametrize("senha", ["marco123", "Tulio2026x", "minha senha marco", "fictício azul"])
def test_recusa_senha_com_o_nome_ou_o_login(senha: str) -> None:
    with pytest.raises(RegraViolada) as erro:
        validar_senha(senha, LOGIN, NOME)
    assert erro.value.codigo == "senha.contem_nome"


@pytest.mark.requisito("DD-83")
@pytest.mark.parametrize("senha", ["curta1", "x" * 65, "ç" * 40])  # 40 "ç" = 80 bytes, acima do bcrypt
def test_recusa_tamanho_fora_de_8_a_64_caracteres_e_72_bytes(senha: str) -> None:
    with pytest.raises(RegraViolada) as erro:
        validar_senha(senha, LOGIN, NOME)
    assert erro.value.codigo == "senha.tamanho"


@pytest.mark.requisito("RNF-613")
@pytest.mark.parametrize(
    ("tentativas", "minutos"),
    [(1, None), (4, None), (5, 5), (6, 10), (7, 20), (8, 40), (9, 60), (10, 60), (200, 60)],
)
def test_bloqueio_dobra_a_cada_falha_ate_o_teto(tentativas: int, minutos: int | None) -> None:
    assert minutos_de_bloqueio(tentativas, limite=5, inicial=5, teto=60) == minutos


@pytest.mark.requisito("RNF-613", "DD-83")
def test_hash_bcrypt_com_custo_12() -> None:
    assert CUSTO == 12
    hasher = Hasher()
    senha_hash = hasher.gerar("cafe com leite")
    assert senha_hash.startswith("$2b$12$") and len(senha_hash) == 60
    assert hasher.conferir("cafe com leite", senha_hash)
    assert not hasher.conferir("cafe com leitE", senha_hash)


@pytest.mark.requisito("RNF-613")
def test_conferir_nunca_falha_com_erro() -> None:
    hasher = Hasher(custo=4)
    senha_hash = hasher.gerar("cafe com leite")
    assert not hasher.conferir("x" * 500, senha_hash)  # acima de 72 bytes: o bcrypt 5 levantaria erro
    assert not hasher.conferir("cafe com leite", None)  # login inexistente: confere contra o fictício


@pytest.mark.requisito("DD-83")
@pytest.mark.parametrize("senha", ["jabuticaba123", "rua123azul", "Quintal2026"])
def test_numero_na_senha_e_aceito_se_ela_nao_cair_nas_regras_da_dd83(senha: str) -> None:
    """Decisão confirmada em 2026-10-13: a DD-83 não proíbe "123" em si. Só recusa a lista de senhas comuns (também
    com número no fim), sequência ou repetição na senha inteira, e senha com o nome ou o login."""
    validar_senha(senha, LOGIN, NOME)
