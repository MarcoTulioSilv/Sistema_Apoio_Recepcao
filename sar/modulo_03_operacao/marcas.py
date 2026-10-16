"""Marca de mês alterado (RF-915, DD-26): toda operação autorizada que alcança mês fechado a grava, com o
responsável, o autorizador, o motivo e a solicitação. O fechamento é conferido antes da mudança, porque a própria
mudança pode reabrir o mês (reabrir uma sessão, por exemplo)."""

from __future__ import annotations

from collections.abc import Iterable
from datetime import date

from sar.modulo_03_operacao.apuracao import mes_fechado
from sar.modulo_08_dados.interfaces.operacao import RepositorioOperacao
from sar.modulo_08_dados.relogio import FUSO_CLINICA
from sar.nucleo.contexto import Contexto
from sar.nucleo.erros import AcessoNegado
from sar.nucleo.portas import Autorizacao
from sar.nucleo.uow import UnidadeDeTrabalho


def meses_fechados(
    uow: UnidadeDeTrabalho, implantacao: date | None, competencias: Iterable[str], autor: Contexto
) -> list[str]:
    hoje = autor.instante.astimezone(FUSO_CLINICA).date()
    return [c for c in sorted(set(competencias)) if mes_fechado(uow, implantacao, c, hoje)[0]]


def gravar_marcas(
    uow: UnidadeDeTrabalho, competencias: Iterable[str], autor: Contexto, autorizacao: Autorizacao
) -> None:
    if autor.usuario_id is None:
        raise AcessoNegado()
    repositorio = uow.repositorio(RepositorioOperacao)
    for comp in competencias:
        repositorio.criar_marca(
            comp, autor.instante, autor.usuario_id, autorizacao.autorizador_id, autorizacao.motivo,
            bytes.fromhex(autorizacao.solicitacao_id),
        )  # fmt: skip
