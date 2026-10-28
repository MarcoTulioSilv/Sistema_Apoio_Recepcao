"""Leitura dos segredos montados no contêiner (DDS §3.9, §12.3). Senhas e chave nunca vêm do banco nem do
repositório; em desenvolvimento, a pasta é indicada por SAR_SEGREDOS (ver segredos/LEIA-ME.md)."""

from __future__ import annotations

import os
import re
from pathlib import Path

from sar.nucleo.erros import ConfiguracaoInvalida

_NOME = re.compile(r"^[a-z][a-z0-9_]*$")


def pasta_segredos() -> Path:
    return Path(os.environ.get("SAR_SEGREDOS", "/run/secrets"))


def ler_segredo(nome: str) -> str:
    """Conteúdo do segredo, sem espaços nas pontas. A mensagem de erro cita o nome, nunca o valor."""
    if not _NOME.match(nome):
        raise ValueError(f"nome de segredo inválido: {nome!r}")
    try:
        valor = (pasta_segredos() / nome).read_text(encoding="utf-8").strip()
    except FileNotFoundError:
        # O caminho não é segredo (só o conteúdo é) e mostra na hora se a variável aponta para a pasta errada.
        raise ConfiguracaoInvalida(
            f"segredo ausente: {nome} em {pasta_segredos()}. Confira SAR_SEGREDOS neste terminal"
        ) from None
    if not valor:
        raise ConfiguracaoInvalida(f"segredo vazio: {nome}")
    return valor
