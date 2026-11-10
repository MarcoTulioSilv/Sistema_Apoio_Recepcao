"""Contrato do MOD-09 Agendamento (DDS §13): a única parte importável de fora do módulo."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum
from typing import Protocol

from sar.nucleo.contexto import Contexto


class Resultado(StrEnum):
    EM_ANDAMENTO = "em_andamento"
    SUCESSO = "sucesso"
    FALHA = "falha"
    SEM_TRABALHO = "sem_trabalho"


# ------------------------------------------------------------------ agenda (§13.1), no fuso da clínica
@dataclass(frozen=True, slots=True)
class Intervalo:
    minutos: int


@dataclass(frozen=True, slots=True)
class Diaria:
    hora: int
    minuto: int


@dataclass(frozen=True, slots=True)
class Domingo:
    """Todo domingo, ou só o primeiro do mês."""

    hora: int
    minuto: int
    primeiro_do_mes: bool = False


@dataclass(frozen=True, slots=True)
class Externa:
    """Fora do worker: pelo sistema operacional (DD-62), à mão (pen drive) ou laço contínuo (DD-63)."""

    descricao: str
    periodo: timedelta | None = None  # o intervalo nominal, para o "roda ao subir"; None quando contínua


Agenda = Intervalo | Diaria | Domingo | Externa


@dataclass(frozen=True, slots=True)
class ResultadoJob:
    itens: int
    cursor: str | None = None  # parou no limite de horário; a próxima execução continua daqui (DD-64)
    sem_trabalho: bool = False  # rodou e não havia o que fazer; conta como execução bem-sucedida (§13.4)


# (contexto de sistema, cursor da execução anterior, segundos até o limite ou None) → resultado
Rotina = Callable[[Contexto, str | None, float | None], ResultadoJob]


@dataclass(frozen=True, slots=True)
class Job:
    """Os campos da §13.3. `rotina` é None nos jobs que rodam fora do worker e só são registrados."""

    nome: str
    rotulo: str
    modulo: str
    agenda: Agenda
    pesado: bool
    intervalo_maximo: timedelta
    roda_ao_subir: bool
    manual_permitida: bool
    rotina: Rotina | None = None
    fora_da_janela: bool = False  # roda ao subir só fora da janela de operação (verificação da cadeia)


@dataclass(frozen=True, slots=True)
class Execucao:
    id: int
    job: str
    inicio: datetime
    fim: datetime | None
    resultado: Resultado
    itens: int | None
    resumo_erro: str | None  # nome do erro, nunca a mensagem (RNF-624)
    parcial: bool  # parou no limite de horário, com cursor


@dataclass(frozen=True, slots=True)
class SituacaoJob:
    nome: str
    rotulo: str
    modulo: str
    quando: str
    intervalo_maximo: timedelta
    ultimo_sucesso: datetime | None
    ultima: Execucao | None
    atrasado: bool


class JobDesconhecido(LookupError):
    pass


class JobEmAndamento(RuntimeError):
    """Outra instância do mesmo job já está rodando (trava, DD-61)."""


class AgendamentoService(Protocol):
    def situacao(self, contexto: Contexto) -> list[SituacaoJob]:
        """Cada job do catálogo com o último sucesso, a última execução e se está atrasado (TI, só leitura)."""
        ...

    def execucoes(self, contexto: Contexto, job: str | None = None, limite: int = 50) -> list[Execucao]: ...

    def executar(self, contexto: Contexto, nome: str, minutos: float | None = None) -> Execucao:
        """Execução manual pela linha de comando do servidor (DD-112), só dos jobs marcados; auditada."""
        ...

    def registrar_externo(
        self, contexto: Contexto, nome: str, resultado: Resultado, inicio: datetime, fim: datetime,
        itens: int | None = None,
    ) -> Execucao:  # fmt: skip
        """Backup e cópia para o pen drive, pelos scripts do servidor (DD-62); auditado."""
        ...
