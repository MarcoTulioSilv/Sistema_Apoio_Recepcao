"""Calendário das sessões de turno e o estado de cada uma pelo relógio (DDS §7.1 e §7.3).

Puro: recebe as escalas, o instante e as antecedências; não lê banco nem relógio. A sessão de cada data e
escala existe por definição a partir da data de implantação (DD-23); sem a data, nenhuma existe (DD-91).
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from enum import StrEnum

from sar.modulo_08_dados.relogio import FUSO_CLINICA

DIAS_SEMANA = ("seg", "ter", "qua", "qui", "sex", "sab", "dom")  # na ordem de date.weekday()
ROTULOS_TURNO = {1: "Primeiro turno", 2: "Segundo turno", 3: "Terceiro turno"}  # DD-75


@dataclass(frozen=True, slots=True)
class Escala:
    id: int
    codigo: str  # 1-seg, 1-ter…: só nas telas da enfermagem (DD-75)
    turno: int
    dias: frozenset[int]  # date.weekday(): 0 = segunda
    inicio: time
    fim: time

    @classmethod
    def de_texto(cls, id: int, codigo: str, turno: int, dias: str, inicio: time, fim: time) -> Escala:
        """`dias` como na tabela: "seg,qua,sex"."""
        return cls(id, codigo, turno, frozenset(DIAS_SEMANA.index(d) for d in dias.split(",")), inicio, fim)

    @property
    def rotulo(self) -> str:
        return ROTULOS_TURNO[self.turno]

    def atende(self, data: date) -> bool:
        return data.weekday() in self.dias


@dataclass(frozen=True, slots=True)
class Sessao:
    data: date
    escala: Escala

    @property
    def inicio(self) -> datetime:
        return datetime.combine(self.data, self.escala.inicio, FUSO_CLINICA)

    @property
    def fim(self) -> datetime:
        return datetime.combine(self.data, self.escala.fim, FUSO_CLINICA)

    @property
    def competencia(self) -> str:
        return competencia(self.data)

    @property
    def ordem(self) -> tuple[date, int]:
        """Ordem cronológica: data e turno (RF-918)."""
        return (self.data, self.escala.turno)


class EstadoSessao(StrEnum):
    FUTURA = "futura"
    EM_PREPARACAO = "em_preparacao"
    DEVIDA = "devida"
    CONFIRMACAO_LIBERADA = "confirmacao_liberada"
    URGENCIA = "urgencia"
    CONFIRMADA = "confirmada"
    NAO_REALIZADA = "nao_realizada"


MARCAVEIS = frozenset(
    {EstadoSessao.EM_PREPARACAO, EstadoSessao.DEVIDA, EstadoSessao.CONFIRMACAO_LIBERADA, EstadoSessao.URGENCIA}
)  # P-13: a partir da preparação
CONFIRMAVEIS = frozenset({EstadoSessao.CONFIRMACAO_LIBERADA, EstadoSessao.URGENCIA})  # DD-32
DEVIDAS = frozenset({EstadoSessao.DEVIDA, EstadoSessao.CONFIRMACAO_LIBERADA, EstadoSessao.URGENCIA})


@dataclass(frozen=True, slots=True)
class Antecedencias:
    """Do MOD-06: `preparacao_turno_antecedencia` e `confirmacao_turno_antecedencia` (DD-30, DD-32)."""

    preparacao: timedelta
    confirmacao: timedelta

    @classmethod
    def em_minutos(cls, preparacao: int, confirmacao: int) -> Antecedencias:
        return cls(timedelta(minutes=preparacao), timedelta(minutes=confirmacao))


def competencia(data: date) -> str:
    return f"{data:%Y-%m}"


def limites_da_competencia(comp: str) -> tuple[date, date]:
    """Primeiro e último dia do mês "AAAA-MM"."""
    ano, mes = int(comp[:4]), int(comp[5:7])
    primeiro = date(ano, mes, 1)
    seguinte = date(ano + mes // 12, mes % 12 + 1, 1)
    return primeiro, seguinte - timedelta(days=1)


def existe(data: date, escala: Escala, implantacao: date | None) -> bool:
    """Há sessão nessa data e escala: dia da escala, a partir da implantação (DD-23, DD-91)."""
    return implantacao is not None and data >= implantacao and escala.atende(data)


def sessoes_entre(escalas: Iterable[Escala], inicio: date, fim: date, implantacao: date | None) -> list[Sessao]:
    """Todas as sessões entre as datas, inclusive, em ordem cronológica."""
    escalas = sorted(escalas, key=lambda e: e.turno)
    dias = (inicio + timedelta(days=n) for n in range((fim - inicio).days + 1))
    return [Sessao(d, e) for d in dias for e in escalas if existe(d, e, implantacao)]


def estado(
    sessao: Sessao,
    agora: datetime,
    antecedencias: Antecedencias,
    *,
    confirmada: bool = False,
    nao_realizada: bool = False,
) -> EstadoSessao:
    """Estado derivado do relógio (§7.3); só confirmação e não realização são gravadas."""
    if nao_realizada:
        return EstadoSessao.NAO_REALIZADA
    if confirmada:
        return EstadoSessao.CONFIRMADA
    if agora < sessao.inicio - antecedencias.preparacao:
        return EstadoSessao.FUTURA
    if agora < sessao.inicio:
        return EstadoSessao.EM_PREPARACAO
    if agora < sessao.fim - antecedencias.confirmacao:
        return EstadoSessao.DEVIDA
    if agora < sessao.fim:
        return EstadoSessao.CONFIRMACAO_LIBERADA
    return EstadoSessao.URGENCIA
