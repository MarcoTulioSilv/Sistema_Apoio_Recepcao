"""Quarentena e cofre de documentos (DDS §8.3, DAS §6.3). Só estes dois componentes tocam arquivo de documento no
disco, e sempre cifrado: nenhum outro vê chave ou imagem em claro.

- Quarentena (DD-34): o que chega da captura, cifrado com a finalidade `quarentena`, numa pasta por ingestão (o id
  aleatório da ingestão é o nome, SEG-07); apagada ao incorporar, rejeitar, cancelar ou expirar.
- Cofre (DD-37, DD-38): o documento incorporado, com chave própria cifrada pela chave mestra (envelope, DD-07) e o id
  do documento como dado associado; gravação em temporário com renomeação atômica antes do commit; toda leitura
  confere o hash.

A quarentena fica fora do backup (SEG-29): sua pasta não pode estar dentro da pasta do cofre.
"""

from __future__ import annotations

import hashlib
import os
import shutil
import time
import uuid
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import IO

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from sar.nucleo.erros import IntegridadeViolada, RegraViolada
from sar.nucleo.portas import Cifra, Finalidade

TAMANHO_CHAVE = 32
TAMANHO_NONCE = 12
BLOCO_LEITURA = 64 * 1024


def sha256(dados: bytes) -> str:
    return hashlib.sha256(dados).hexdigest()


def hash_das_paginas(hashes: Iterable[str]) -> str:
    """O hash de entrada da ingestão: o das páginas na ordem, encadeado (SEG-27)."""
    return sha256("\n".join(hashes).encode())


def ler_limitado(fluxo: IO[bytes], limite: int) -> bytes:
    """Lê o envio em blocos e para assim que passa do limite, sem guardar o excesso (SEG-06)."""
    partes: list[bytes] = []
    total = 0
    while bloco := fluxo.read(BLOCO_LEITURA):
        total += len(bloco)
        if total > limite:
            raise RegraViolada("arquivo.tamanho")
        partes.append(bloco)
    return b"".join(partes)


def _dentro(pasta: Path, raiz: Path) -> bool:
    try:
        pasta.resolve().relative_to(raiz.resolve())
    except ValueError:
        return False
    return True


@dataclass(frozen=True, slots=True)
class Pastas:
    cofre: Path
    quarentena: Path

    def __post_init__(self) -> None:
        if _dentro(self.quarentena, self.cofre) or _dentro(self.cofre, self.quarentena):
            raise ValueError("a quarentena e o cofre ficam em pastas separadas: só o cofre vai para o backup (SEG-29)")


class Quarentena:
    def __init__(self, raiz: Path, cifra: Cifra) -> None:
        self._raiz = raiz
        self._cifra = cifra

    def _pasta(self, ingestao_id: bytes) -> Path:
        return self._raiz / ingestao_id.hex()

    @staticmethod
    def _associado(ingestao_id: bytes, nome: str) -> bytes:
        return ingestao_id + nome.encode()

    def gravar(self, ingestao_id: bytes, nome: str, conteudo: bytes) -> str:
        """Grava cifrado e devolve o hash do conteúdo em claro."""
        pasta = self._pasta(ingestao_id)
        pasta.mkdir(parents=True, exist_ok=True)
        nonce, cifrado = self._cifra.cifrar(Finalidade.QUARENTENA, conteudo, self._associado(ingestao_id, nome))
        temporario = pasta / f".{nome}.tmp"
        temporario.write_bytes(nonce + cifrado)
        os.replace(temporario, pasta / nome)
        return sha256(conteudo)

    def ler(self, ingestao_id: bytes, nome: str) -> bytes:
        caminho = self._pasta(ingestao_id) / nome
        try:
            bruto = caminho.read_bytes()
        except FileNotFoundError:
            raise IntegridadeViolada("arquivo da quarentena ausente") from None
        nonce, cifrado = bruto[:TAMANHO_NONCE], bruto[TAMANHO_NONCE:]
        return self._cifra.decifrar(Finalidade.QUARENTENA, nonce, cifrado, self._associado(ingestao_id, nome))

    def nomes(self, ingestao_id: bytes) -> list[str]:
        pasta = self._pasta(ingestao_id)
        if not pasta.is_dir():
            return []
        return sorted(p.name for p in pasta.iterdir() if not p.name.startswith("."))

    def apagar(self, ingestao_id: bytes) -> None:
        shutil.rmtree(self._pasta(ingestao_id), ignore_errors=True)

    def ingestoes(self) -> list[bytes]:
        """As pastas presentes, para a limpeza das que sobraram de ingestão encerrada."""
        if not self._raiz.is_dir():
            return []
        return [bytes.fromhex(p.name) for p in self._raiz.iterdir() if p.is_dir() and len(p.name) == 32]


@dataclass(frozen=True, slots=True)
class Guardado:
    arquivo: str  # nome aleatório (SEG-07), sem relação com o paciente nem com o tipo
    chave_cifrada: bytes  # nonce + chave do documento cifrada pela chave mestra
    nonce: bytes  # do arquivo
    hash_sha256: str  # do conteúdo em claro (SEG-15)


class Cofre:
    def __init__(self, raiz: Path, cifra: Cifra) -> None:
        self._raiz = raiz
        self._cifra = cifra

    def _caminho(self, arquivo: str) -> Path:
        return self._raiz / arquivo[:2] / arquivo

    def guardar(self, documento_id: bytes, conteudo: bytes) -> Guardado:
        """Fase do arquivo (DD-37): cifra, grava em temporário e renomeia. Quem chama grava a linha na mesma
        transação; se ela falhar, sobra no máximo um arquivo órfão, que a varredura remove."""
        chave = os.urandom(TAMANHO_CHAVE)
        nonce = os.urandom(TAMANHO_NONCE)
        cifrado = AESGCM(chave).encrypt(nonce, conteudo, documento_id)
        nonce_chave, chave_cifrada = self._cifra.cifrar(Finalidade.DOCUMENTOS, chave, documento_id)
        arquivo = str(uuid.uuid4())
        destino = self._caminho(arquivo)
        destino.parent.mkdir(parents=True, exist_ok=True)
        temporario = destino.with_name(f".{arquivo}.tmp")
        temporario.write_bytes(cifrado)
        os.replace(temporario, destino)
        return Guardado(arquivo, nonce_chave + chave_cifrada, nonce, sha256(conteudo))

    def ler(self, documento_id: bytes, arquivo: str, chave_cifrada: bytes, nonce: bytes, hash_sha256: str) -> bytes:
        """Decifra em memória e confere o hash (DD-38). IntegridadeViolada se o arquivo sumiu, foi alterado ou não
        confere com o hash gravado."""
        try:
            cifrado = self._caminho(arquivo).read_bytes()
        except FileNotFoundError:
            raise IntegridadeViolada("arquivo do documento ausente") from None
        chave = self._cifra.decifrar(
            Finalidade.DOCUMENTOS, chave_cifrada[:TAMANHO_NONCE], chave_cifrada[TAMANHO_NONCE:], documento_id
        )
        try:
            conteudo = AESGCM(chave).decrypt(nonce, cifrado, documento_id)
        except InvalidTag:
            raise IntegridadeViolada("arquivo do documento alterado") from None
        if sha256(conteudo) != hash_sha256:
            raise IntegridadeViolada("hash do documento não confere")
        return conteudo

    def destruir(self, arquivo: str) -> None:
        """Descarte (DD-04): o arquivo sai do cofre; quem chama apaga a chave na linha."""
        self._caminho(arquivo).unlink(missing_ok=True)

    def orfaos(self, conhecidos: set[str], mais_velhos_que: float = 0) -> list[str]:
        """Arquivos sem linha correspondente (DD-37) e temporários esquecidos, pelo caminho relativo ao cofre. Com
        `mais_velhos_que` (segundos), só os modificados antes disso: o arquivo de uma incorporação ainda sem commit
        também não tem linha."""
        if not self._raiz.is_dir():
            return []
        limite = time.time() - mais_velhos_que
        return sorted(
            p.relative_to(self._raiz).as_posix()
            for p in self._raiz.glob("*/*")
            if p.is_file() and p.name not in conhecidos and p.stat().st_mtime <= limite
        )

    def remover_orfao(self, relativo: str) -> None:
        caminho = (self._raiz / relativo).resolve()
        if not _dentro(caminho, self._raiz):
            raise ValueError("caminho fora do cofre")
        caminho.unlink(missing_ok=True)
