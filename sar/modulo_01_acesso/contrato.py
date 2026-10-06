"""Contrato do MOD-01 Acesso e auditoria (DDS §5.4): a única parte importável de fora do módulo."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Protocol

from sar.nucleo.contexto import Contexto
from sar.nucleo.uow import UnidadeDeTrabalho


class AuditService(Protocol):
    def registrar(
        self,
        uow: UnidadeDeTrabalho,
        contexto: Contexto,
        operacao: str,
        entidade: str,
        entidade_id: str | None,
        alteracoes: Mapping[str, tuple[object, object]] | None = None,
        motivo: str | None = None,
        autorizador_id: int | None = None,
    ) -> None:
        """Registra na mesma transação da operação; a falha desfaz a operação (DD-03). Só os campos que
        mudaram entram (DD-10); bytes, ponto flutuante e instante sem fuso são recusados na hora."""
        ...
