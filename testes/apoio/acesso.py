"""Apoio dos testes de acesso: senha de teste, hasher rápido e parâmetros nos valores padrão."""

from __future__ import annotations

from collections.abc import Callable
from datetime import date

from sar.modulo_01_acesso.senhas import Hasher
from sar.nucleo.parametros import PARAMETROS

SENHA = "cafe com leite"
HASHER = Hasher(custo=4)  # rápido nos testes; o custo 12 de produção é conferido no teste de unidade
HASH = HASHER.gerar(SENHA)

CriarUsuario = Callable[..., int]


class ParametrosPadrao:
    """LeitorParametros com os padrões do núcleo: 5 tentativas, bloqueio de 5 a 60 min, inatividade de 10 min,
    sessão de até 12 h. Um valor pode ser trocado no teste."""

    def __init__(self, **trocas: int) -> None:
        self._trocas = trocas

    def valor(self, nome: str) -> int | bool | date | None:
        return self._trocas.get(nome, PARAMETROS[nome].padrao)
