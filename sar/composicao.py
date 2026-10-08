"""Raiz de composição (DD-02, DDS §3.4): o único lugar que liga implementações às portas do núcleo.

A partir do Incremento 1, também registra aqui as assinaturas de eventos, os executores de portas, as
fontes de pendência e os jobs de cada módulo.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from enum import Enum

from sqlalchemy import Engine

from sar.modulo_01_acesso.contrato import AuditService, IntegridadeService
from sar.modulo_01_acesso.servicos import ServicoAuditoria, ServicoIntegridade, manipulador_aviso_integridade
from sar.modulo_08_dados.cadeia import gravar_encadeado
from sar.modulo_08_dados.cifra import CifraAesGcm
from sar.modulo_08_dados.interfaces.trilha import RepositorioExpurgo, RepositorioTrilha
from sar.modulo_08_dados.relogio import RelogioSistema
from sar.modulo_08_dados.repositorios.trilha import RepositorioExpurgoSQL, RepositorioTrilhaSQL
from sar.modulo_08_dados.uow import ExecutorSQL, FabricaRepositorio, GravadorAuditoria, UnidadeDeTrabalhoSQL
from sar.nucleo.eventos import Barramento, CadeiaDivergente
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


# Interface do repositório (sem SQLAlchemy, importável pelos módulos) → implementação SQL.
REPOSITORIOS: dict[type, FabricaRepositorio] = {
    RepositorioTrilha: RepositorioTrilhaSQL,
    RepositorioExpurgo: RepositorioExpurgoSQL,
}


def montar_barramento(relogio: Relogio) -> Barramento:
    """Consumidores dos eventos de domínio (DDS §3.11)."""
    barramento = Barramento()
    barramento.assinar(CadeiaDivergente, manipulador_aviso_integridade(relogio))
    return barramento


def montar_executor(
    engine: Engine, barramento: Barramento, gravar_auditoria: GravadorAuditoria = gravar_encadeado
) -> ExecutorSQL:
    """O gravador padrão é a cadeia encadeada (DD-03); outro gravador só nos testes de unidade, sem banco."""

    def nova_unidade() -> UnidadeDeTrabalhoSQL:
        return UnidadeDeTrabalhoSQL(engine, barramento, gravar_auditoria, REPOSITORIOS)

    return ExecutorSQL(nova_unidade)


def compor_auditoria(engine: Engine, engine_expurgo: Engine | None = None) -> ServicoAuditoria:
    """Só a trilha, sem a cifra: o que o worker e a linha de comando precisam para verificar e expurgar."""
    barramento = montar_barramento(RelogioSistema())
    expurgo = montar_executor(engine_expurgo, barramento) if engine_expurgo is not None else None
    return ServicoAuditoria(montar_executor(engine, barramento), expurgo)


@dataclass(frozen=True, slots=True)
class Componentes:
    relogio: Relogio
    cifra: Cifra
    barramento: Barramento
    executar: ExecutorDeOperacao
    auditoria: AuditService
    integridade: IntegridadeService


def compor(engine: Engine, chave_mestra: bytes, gravar_auditoria: GravadorAuditoria = gravar_encadeado) -> Componentes:
    relogio = RelogioSistema()
    barramento = montar_barramento(relogio)
    executar = montar_executor(engine, barramento, gravar_auditoria)
    auditoria = ServicoAuditoria(executar)
    return Componentes(
        relogio=relogio,
        cifra=CifraAesGcm(chave_mestra),
        barramento=barramento,
        executar=executar,
        auditoria=auditoria,
        integridade=ServicoIntegridade(executar, auditoria),
    )
