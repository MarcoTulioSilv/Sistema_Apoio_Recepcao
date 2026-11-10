"""Registro de execução dos jobs (DDS §13.4, DD-61) e a trava nomeada no banco."""

from __future__ import annotations

from contextlib import AbstractContextManager
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol


@dataclass(frozen=True, slots=True)
class ExecucaoGravada:
    id: int
    job: str
    inicio: datetime
    fim: datetime | None
    resultado: str  # em_andamento, sucesso, falha, sem_trabalho
    itens: int | None
    resumo_erro: str | None
    cursor: str | None


class RepositorioAgendamento(Protocol):
    def abrir(self, job: str, inicio: datetime) -> int:
        """Linha "em_andamento"; o id é fechado no fim da execução."""
        ...

    def fechar(
        self, id: int, fim: datetime, resultado: str, itens: int | None, resumo_erro: str | None, cursor: str | None
    ) -> None: ...

    def registrar(
        self, job: str, inicio: datetime, fim: datetime, resultado: str, itens: int | None, resumo_erro: str | None
    ) -> int:
        """Execução já terminada, feita fora do worker (backup pelo sistema operacional, DD-62)."""
        ...

    def por_id(self, id: int) -> ExecucaoGravada: ...

    def ultimos_sucessos(self, jobs: list[str] | None = None) -> dict[str, datetime]:
        """Início da última execução bem-sucedida e completa (sucesso sem cursor, ou sem trabalho) de cada job, numa
        consulta só."""
        ...

    def ultima(self, job: str, resultado: str | None = None) -> ExecucaoGravada | None:
        """A execução mais recente do job, ou a mais recente com o resultado dado."""
        ...

    def recentes(self, limite: int, job: str | None = None) -> list[ExecucaoGravada]:
        """Da mais nova para a mais antiga."""
        ...


class Trava(Protocol):
    """Trava nomeada no banco (DD-61), fora da unidade de trabalho: dura a execução inteira do job."""

    def obter(self, nome: str, espera_segundos: float) -> AbstractContextManager[bool]:
        """True se obteve dentro da espera; liberada na saída do bloco."""
        ...
