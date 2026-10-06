"""Eventos de domínio (DDS §3.11, DD-15). Síncronos, despachados antes do commit, na mesma transação.

Regras (DD-74): evento carrega só identificadores, datas e códigos — nunca dado pessoal; e só existe
evento com consumidor. Efeitos em que a ordem importa (encerramento de período, anulação) usam portas.

| Evento               | Publicado por | Consumido por                                          |
|----------------------|---------------|--------------------------------------------------------|
| UsuarioInativado     | MOD-01        | MOD-01: encerra as sessões do usuário                  |
| CadeiaDivergente     | MOD-01        | MOD-01: abre o aviso de integridade (DEC-43)           |
| DocumentoIncorporado | MOD-04        | MOD-02: comprovante do evento; MOD-03: termos (RF-809) |
| DocumentoRevinculado | MOD-04        | MOD-02 e MOD-03: desfazem vínculos do paciente antigo  |
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, TypeVar

if TYPE_CHECKING:
    from sar.nucleo.uow import UnidadeDeTrabalho


@dataclass(frozen=True, slots=True)
class EventoDominio:
    pass


# ---- MOD-01
@dataclass(frozen=True, slots=True)
class UsuarioInativado(EventoDominio):
    usuario_id: int


@dataclass(frozen=True, slots=True)
class CadeiaDivergente(EventoDominio):
    registro_divergente_id: int


# ---- MOD-04
@dataclass(frozen=True, slots=True)
class DocumentoIncorporado(EventoDominio):
    documento_id: bytes
    paciente_id: int
    tipo: str
    vinculo: str | None  # opaco para o MOD-04; interpretado por quem abriu a ingestão


@dataclass(frozen=True, slots=True)
class DocumentoRevinculado(EventoDominio):
    documento_id: bytes
    paciente_anterior_id: int
    paciente_novo_id: int


E = TypeVar("E", bound=EventoDominio)
Manipulador = Callable[["UnidadeDeTrabalho", E], None]


class Barramento:
    """Registro de manipuladores. Preenchido só na raiz de composição (sar/composicao.py)."""

    def __init__(self) -> None:
        self._manipuladores: dict[type[EventoDominio], list[Manipulador[Any]]] = defaultdict(list)

    def assinar(self, tipo: type[E], manipulador: Manipulador[E]) -> None:
        self._manipuladores[tipo].append(manipulador)

    def despachar(self, uow: UnidadeDeTrabalho, evento: EventoDominio) -> None:
        """Chamado pela unidade de trabalho antes do commit. Exceção desfaz a operação inteira."""
        for manipulador in self._manipuladores[type(evento)]:
            manipulador(uow, evento)
