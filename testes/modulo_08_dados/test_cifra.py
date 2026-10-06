from __future__ import annotations

import base64
from pathlib import Path

import pytest
from hypothesis import given
from hypothesis import strategies as st

from sar.modulo_08_dados.cifra import CifraAesGcm, carregar_chave_mestra
from sar.nucleo.erros import IntegridadeViolada
from sar.nucleo.portas import Finalidade

CHAVE = bytes(range(32))
CIFRA = CifraAesGcm(CHAVE)


@pytest.mark.requisito("DD-07")
@given(dados=st.binary(max_size=4096), associado=st.binary(max_size=64), finalidade=st.sampled_from(Finalidade))
def test_decifra_o_que_cifrou(dados: bytes, associado: bytes, finalidade: Finalidade) -> None:
    nonce, cifrado = CIFRA.cifrar(finalidade, dados, associado)
    assert len(nonce) == 12
    assert CIFRA.decifrar(finalidade, nonce, cifrado, associado) == dados


@pytest.mark.requisito("DD-07")
def test_cifrado_de_um_registro_nao_abre_em_outro() -> None:
    nonce, cifrado = CIFRA.cifrar(Finalidade.RASCUNHOS, b"rascunho", b"rascunho:1")
    with pytest.raises(IntegridadeViolada):
        CIFRA.decifrar(Finalidade.RASCUNHOS, nonce, cifrado, b"rascunho:2")


@pytest.mark.requisito("DD-07")
def test_chave_de_uma_finalidade_nao_abre_outra() -> None:
    nonce, cifrado = CIFRA.cifrar(Finalidade.RASCUNHOS, b"rascunho", b"1")
    with pytest.raises(IntegridadeViolada):
        CIFRA.decifrar(Finalidade.DOCUMENTOS, nonce, cifrado, b"1")


@pytest.mark.requisito("DD-07")
def test_cifrado_adulterado_e_recusado() -> None:
    nonce, cifrado = CIFRA.cifrar(Finalidade.DOCUMENTOS, b"documento", b"1")
    adulterado = bytes([cifrado[0] ^ 1]) + cifrado[1:]
    with pytest.raises(IntegridadeViolada):
        CIFRA.decifrar(Finalidade.DOCUMENTOS, nonce, adulterado, b"1")


@pytest.mark.requisito("DD-07")
def test_nonce_nunca_se_repete_e_texto_nao_aparece_no_cifrado() -> None:
    resultados = [CIFRA.cifrar(Finalidade.DOCUMENTOS, b"mesmo texto", b"1") for _ in range(1000)]
    assert len({nonce for nonce, _ in resultados}) == 1000
    assert all(b"mesmo texto" not in cifrado for _, cifrado in resultados)


@pytest.mark.requisito("DD-07")
def test_outra_chave_mestra_nao_abre() -> None:
    nonce, cifrado = CIFRA.cifrar(Finalidade.DOCUMENTOS, b"documento", b"1")
    with pytest.raises(IntegridadeViolada):
        CifraAesGcm(bytes(32)).decifrar(Finalidade.DOCUMENTOS, nonce, cifrado, b"1")


@pytest.mark.requisito("DD-07")
@pytest.mark.parametrize("tamanho", [0, 16, 31, 33])
def test_recusa_chave_mestra_de_tamanho_errado(tamanho: int) -> None:
    with pytest.raises(ValueError):
        CifraAesGcm(bytes(tamanho))


@pytest.mark.requisito("DD-07")
def test_carrega_chave_mestra_do_segredo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SAR_SEGREDOS", str(tmp_path))
    (tmp_path / "chave_mestra").write_text(base64.b64encode(CHAVE).decode() + "\n")
    assert carregar_chave_mestra() == CHAVE


@pytest.mark.requisito("DD-07")
@pytest.mark.parametrize("conteudo", ["não é base64!", base64.b64encode(bytes(16)).decode()])
def test_recusa_segredo_de_chave_invalido(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, conteudo: str) -> None:
    monkeypatch.setenv("SAR_SEGREDOS", str(tmp_path))
    (tmp_path / "chave_mestra").write_text(conteudo, encoding="utf-8")
    with pytest.raises(RuntimeError) as erro:
        carregar_chave_mestra()
    assert conteudo not in str(erro.value)
