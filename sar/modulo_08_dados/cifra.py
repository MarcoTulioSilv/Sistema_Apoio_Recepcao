"""Cifragem por finalidade (DD-07, DDS §3.9): AES-256-GCM com uma chave por finalidade, derivada da chave
mestra por HKDF-SHA256. O dado associado amarra o cifrado ao registro dono."""

from __future__ import annotations

import base64
import os

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.hashes import SHA256
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

from sar.modulo_08_dados.segredos import ler_segredo
from sar.nucleo.erros import IntegridadeViolada
from sar.nucleo.portas import Finalidade

TAMANHO_CHAVE = 32
TAMANHO_NONCE = 12


def _derivar(chave_mestra: bytes, finalidade: Finalidade) -> bytes:
    # O rótulo entra na derivação: mudá-lo torna ilegível tudo o que já foi cifrado.
    return HKDF(algorithm=SHA256(), length=TAMANHO_CHAVE, salt=None, info=f"sar/{finalidade.value}".encode()).derive(
        chave_mestra
    )


class CifraAesGcm:
    def __init__(self, chave_mestra: bytes) -> None:
        if len(chave_mestra) != TAMANHO_CHAVE:
            raise ValueError(f"a chave mestra deve ter {TAMANHO_CHAVE} bytes")
        self._aead = {f: AESGCM(_derivar(chave_mestra, f)) for f in Finalidade}

    def cifrar(self, finalidade: Finalidade, dados: bytes, associado: bytes) -> tuple[bytes, bytes]:
        nonce = os.urandom(TAMANHO_NONCE)  # aleatório por cifragem; nunca reutilizado com a mesma chave
        return nonce, self._aead[finalidade].encrypt(nonce, dados, associado)

    def decifrar(self, finalidade: Finalidade, nonce: bytes, cifrado: bytes, associado: bytes) -> bytes:
        """IntegridadeViolada se o cifrado, o nonce, o dado associado ou a finalidade não conferem."""
        try:
            return self._aead[finalidade].decrypt(nonce, cifrado, associado)
        except InvalidTag:
            raise IntegridadeViolada("cifrado não confere") from None


def carregar_chave_mestra() -> bytes:
    """Lê o segredo chave_mestra: 32 bytes em base64."""
    try:
        chave = base64.b64decode(ler_segredo("chave_mestra"), validate=True)
    except ValueError:  # binascii.Error é subclasse; texto não ASCII também chega aqui
        raise RuntimeError("segredo chave_mestra não está em base64") from None
    if len(chave) != TAMANHO_CHAVE:
        raise RuntimeError(f"segredo chave_mestra deve ter {TAMANHO_CHAVE} bytes")
    return chave
