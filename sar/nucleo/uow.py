"""Contrato da unidade de trabalho (DDS §3.3, §12.1). Implementada no MOD-08."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol, TypeVar

from sar.nucleo.contexto import Contexto
from sar.nucleo.eventos import EventoDominio

R = TypeVar("R")


@dataclass(frozen=True, slots=True)
class RegistroAuditoria:
    contexto: Contexto
    operacao: str  # código do catálogo de operações (§4)
    entidade: str
    entidade_id: str | None
    alteracoes: dict[str, tuple[object, object]] | None  # só campos alterados (DD-10)
    motivo: str | None = None
    autorizador_id: int | None = None


class UnidadeDeTrabalho(Protocol):
    """Uma operação de negócio, uma transação.

    Ordem no fechamento: despacha eventos (DD-15) → trava a cabeça da cadeia e grava a auditoria
    (DD-03, DD-71) → commit → executa as ações de depois do commit. Em impasse, a operação inteira é
    repetida até três vezes (DD-59), por isso nada fora do banco acontece antes do commit.
    """

    def __enter__(self) -> UnidadeDeTrabalho: ...

    def __exit__(self, *exc: object) -> None: ...

    def repositorio(self, tipo: type[R]) -> R: ...

    def publicar(self, evento: EventoDominio) -> None: ...

    def auditar(self, registro: RegistroAuditoria) -> None: ...

    def depois_do_commit(self, acao: Callable[[], None]) -> None:
        """Ex.: apagar o arquivo da quarentena depois de incorporar o documento (DD-37)."""
        ...

    def confirmar(self) -> None: ...


class ExecutorDeOperacao(Protocol):
    """Como o serviço público abre e fecha a unidade de trabalho (DDS §3.3).

    Abre uma unidade nova, executa a operação e confirma no fim. Em impasse ou tempo de trava esgotado,
    descarta tudo e repete a operação inteira, até três tentativas (DD-59). Por isso a operação recebe a
    unidade como argumento: um bloco `with` não pode ser repetido.
    """

    def __call__(self, operacao: Callable[[UnidadeDeTrabalho], R]) -> R: ...
