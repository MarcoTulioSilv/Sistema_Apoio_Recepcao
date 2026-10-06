"""Parâmetros tipados (DD-48, DDS §10.1). A declaração fica aqui; o valor, no MOD-06.

Todo módulo lê parâmetros pela porta LeitorParametros, sem importar o MOD-06 (DD-73).
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from enum import Enum
from typing import Protocol

from sar.nucleo.contexto import Perfil


class Unidade(str, Enum):
    MINUTOS = "min"
    HORAS = "h"
    DIAS = "dias"
    QUANTIDADE = "qtd"
    BOOLEANO = "bool"
    DATA = "data"


@dataclass(frozen=True, slots=True)
class Parametro:
    nome: str
    unidade: Unidade
    padrao: int | bool | date | None
    minimo: int | None
    maximo: int | None
    editor: Perfil  # ADMINISTRACAO (operacional) ou TI (técnico)
    imutavel_apos_uso: bool = False


PARAMETROS: dict[str, Parametro] = {p.nome: p for p in [
    Parametro("preparacao_turno_antecedencia", Unidade.MINUTOS, 60, 15, 120, Perfil.ADMINISTRACAO),
    Parametro("confirmacao_turno_antecedencia", Unidade.MINUTOS, 60, 15, 120, Perfil.ADMINISTRACAO),
    Parametro("rascunho_prazo", Unidade.DIAS, 3, 1, 30, Perfil.ADMINISTRACAO),
    Parametro("rascunho_aviso", Unidade.DIAS, 1, 1, 7, Perfil.ADMINISTRACAO),
    Parametro("titular_prazo", Unidade.DIAS, 15, 1, 15, Perfil.ADMINISTRACAO),
    Parametro("sessao_inatividade", Unidade.MINUTOS, 10, 2, 30, Perfil.TI),
    Parametro("sessao_duracao_maxima", Unidade.HORAS, 12, 1, 16, Perfil.TI),
    Parametro("login_tentativas", Unidade.QUANTIDADE, 5, 3, 10, Perfil.TI),
    Parametro("login_bloqueio_inicial", Unidade.MINUTOS, 5, 1, 30, Perfil.TI),
    Parametro("login_bloqueio_teto", Unidade.MINUTOS, 60, 15, 240, Perfil.TI),
    Parametro("captura_token_validade", Unidade.MINUTOS, 10, 2, 30, Perfil.TI),
    Parametro("quarentena_prazo", Unidade.HORAS, 24, 1, 72, Perfil.TI),
    Parametro("extracao_ligada", Unidade.BOOLEANO, True, None, None, Perfil.TI),
    Parametro("antimalware_idade_maxima", Unidade.HORAS, 48, 24, 168, Perfil.TI),
    Parametro("data_implantacao", Unidade.DATA, None, None, None, Perfil.TI, imutavel_apos_uso=True),
]}


class LeitorParametros(Protocol):
    def valor(self, nome: str) -> int | bool | date | None:
        """Valor vigente, sempre dentro dos limites declarados; lido por operação, sem cache (DD-48)."""
        ...
