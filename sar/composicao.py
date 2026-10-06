"""Raiz de composição (DD-02, DDS §3.4): o único lugar que liga implementações às portas do núcleo.

A partir do Incremento 1, também registra aqui as assinaturas de eventos, os executores de portas, as
fontes de pendência e os jobs de cada módulo.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from enum import Enum

from sqlalchemy import Engine

from sar.modulo_08_dados.cifra import CifraAesGcm
from sar.modulo_08_dados.relogio import RelogioSistema
from sar.modulo_08_dados.uow import ExecutorSQL, FabricaRepositorio, GravadorAuditoria, UnidadeDeTrabalhoSQL
from sar.nucleo.eventos import Barramento
from sar.nucleo.portas import Cifra, Relogio
from sar.nucleo.uow import ExecutorDeOperacao


class Ambiente(str, Enum):
    DESENVOLVIMENTO = "desenvolvimento"
    PRODUCAO = "producao"


def ambiente_atual() -> Ambiente:
    """SAR_AMBIENTE; sem a variável, produção (DD-85): o que só existe em desenvolvimento nunca liga por
    esquecimento. Valor desconhecido é erro, não palpite."""
    valor = os.environ.get("SAR_AMBIENTE", Ambiente.PRODUCAO.value)
    try:
        return Ambiente(valor)
    except ValueError:
        raise RuntimeError("SAR_AMBIENTE deve ser 'desenvolvimento' ou 'producao'") from None


@dataclass(frozen=True, slots=True)
class Componentes:
    relogio: Relogio
    cifra: Cifra
    barramento: Barramento
    executar: ExecutorDeOperacao


def compor(engine: Engine, chave_mestra: bytes, gravar_auditoria: GravadorAuditoria) -> Componentes:
    """O gravador de auditoria é obrigatório: nenhuma operação confirma sem gravar a sua trilha (DD-03)."""
    barramento = Barramento()
    repositorios: dict[type, FabricaRepositorio] = {}

    def nova_unidade() -> UnidadeDeTrabalhoSQL:
        return UnidadeDeTrabalhoSQL(engine, barramento, gravar_auditoria, repositorios)

    return Componentes(
        relogio=RelogioSistema(),
        cifra=CifraAesGcm(chave_mestra),
        barramento=barramento,
        executar=ExecutorSQL(nova_unidade),
    )
