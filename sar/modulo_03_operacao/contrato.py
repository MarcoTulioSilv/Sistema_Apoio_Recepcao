"""Contrato do MOD-03 Operação (DDS §7.10): a única parte importável de fora do módulo."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, time
from enum import StrEnum
from typing import Protocol

from sar.nucleo.contexto import Contexto

DIAS_SEMANA = ("seg", "ter", "qua", "qui", "sex", "sab", "dom")  # na ordem de date.weekday()
ROTULOS_TURNO = {1: "Primeiro turno", 2: "Segundo turno", 3: "Terceiro turno"}  # DD-75


@dataclass(frozen=True, slots=True)
class Escala:
    """Uma das seis escalas fixas (DEC-52, P-14)."""

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
        """Primeiro, segundo ou terceiro turno: o nome que a recepção vê (DD-75)."""
        return ROTULOS_TURNO[self.turno]

    def atende(self, data: date) -> bool:
        return data.weekday() in self.dias


class EstadoSessao(StrEnum):
    """Derivado do relógio, salvo confirmada e não realizada (§7.3, DD-23)."""

    FUTURA = "futura"
    EM_PREPARACAO = "em_preparacao"
    DEVIDA = "devida"
    CONFIRMACAO_LIBERADA = "confirmacao_liberada"
    URGENCIA = "urgencia"
    CONFIRMADA = "confirmada"
    NAO_REALIZADA = "nao_realizada"


@dataclass(frozen=True, slots=True)
class ContagemEscalas:
    """RF-404, sem limite; os sem alocação aparecem explicitamente (RF-403)."""

    por_escala: Mapping[int, int]  # id da escala → pacientes alocados
    sem_alocacao: int


# ------------------------------------------------------------------ serviços para a interface
class EscalaService(Protocol):
    """Escalas da enfermagem (RF-401 a RF-406). Registrar e cancelar só pela enfermagem, auditado com o autor;
    `RequerAutorizacao` quando alcança sessão já confirmada."""

    def escalas(self, contexto: Contexto) -> list[Escala]: ...

    def contagem(self, contexto: Contexto, data: date) -> ContagemEscalas:
        """Pacientes com período aberto na data, pela alocação vigente."""
        ...

    def alocar(self, contexto: Contexto, paciente_id: int, escala_id: int | None, inicio: date) -> None:
        """Nova vigência a partir do início no período que cobre a data; None = sem alocação (DD-27). A mesma
        escala que já vale não grava nada. RegraViolada: "INV-03" (sem período na data), "INV-01" (depois do
        óbito), "escala.inexistente". RequerAutorizacao("operacao.alocacao.registrar_retroativa") se alguma sessão
        confirmada é afetada. NaoEncontrado (paciente)."""
        ...

    def alocar_em_lote(self, contexto: Contexto, alocacoes: Sequence[tuple[int, int | None]], inicio: date) -> None:
        """Vários pacientes de uma vez (RF-405), cada um na sua escala, numa transação. As RegraViolada do alocar
        trazem o paciente no detalhe ({"paciente_id": id})."""
        ...

    def registrar_troca(
        self, contexto: Contexto, paciente_id: int, origem: date, destino: date, escala_destino_id: int
    ) -> int:
        """Troca pontual (RF-503, P-10, P-11). RegraViolada: "P-11" (meses diferentes; a tela orienta a registrar
        ausência num mês e extra planejada no outro), "troca.origem_fora_da_escala", "troca.destino_na_propria_escala",
        "sessao.inexistente", "INV-04", "INV-01", "troca.origem_repetida". RequerAutorizacao("operacao.sessao.reabrir")
        se a origem ou o destino já foi confirmado."""
        ...

    def cancelar_troca(self, contexto: Contexto, troca_id: int, motivo: str | None = None) -> None:
        """RequerAutorizacao("operacao.troca.cancelar_realizada") se a origem ou o destino já foi confirmado.
        NaoEncontrado se não existe ou já foi cancelada."""
        ...

    def registrar_extra(self, contexto: Contexto, paciente_id: int, data: date, escala_id: int) -> int:
        """Extra planejada (RF-504). RegraViolada: "extra.na_propria_escala", "sessao.inexistente", "INV-04",
        "INV-01", "extra.repetida". RequerAutorizacao("operacao.sessao.reabrir") se a sessão já foi confirmada."""
        ...

    def cancelar_extra(self, contexto: Contexto, extra_id: int, motivo: str | None = None) -> None:
        """RequerAutorizacao("operacao.sessao.reabrir") se a sessão já foi confirmada. NaoEncontrado."""
        ...
