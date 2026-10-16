"""A lista esperada de uma sessão (DDS §7.2), usada na tela do turno e na confirmação.

Pura: recebe a situação de cada paciente candidato e as exceções já gravadas na sessão. Quem consulta reúne os
candidatos (alocados na escala, com troca ou extra para a sessão e os que têm exceção gravada) e ordena pelo nome.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import date
from enum import StrEnum

from sar.modulo_03_operacao.calendario import Sessao
from sar.modulo_03_operacao.compensacao import Periodo, Troca


class Origem(StrEnum):
    ALOCADO = "alocado"
    TROCA_CHEGANDO = "troca_chegando"
    EXTRA_PLANEJADA = "extra_planejada"
    TROCA_SAINDO = "troca_saindo"  # pré-marcado como ausente (P-10)
    ACRESCENTADO = "acrescentado"  # pela recepção, vindo das presenças gravadas (DD-24)


@dataclass(frozen=True, slots=True)
class SituacaoPaciente:
    paciente_id: int
    periodos: tuple[Periodo, ...]
    obito: date | None = None
    trocas: tuple[Troca, ...] = ()  # não canceladas
    extras: tuple[Sessao, ...] = ()  # extras planejadas não canceladas


@dataclass(frozen=True, slots=True)
class Esperado:
    paciente_id: int
    origem: Origem
    presente: bool  # o padrão da origem, ou a exceção gravada
    marcado: bool  # há exceção gravada para o paciente nesta sessão


def _esperado(sessao: Sessao, paciente: SituacaoPaciente, gravado: bool | None) -> Esperado | None:
    data = sessao.data
    if paciente.obito is not None and paciente.obito < data:  # INV-01
        return None
    periodo = next((p for p in paciente.periodos if p.contem(data)), None)
    if periodo is None:  # INV-04: só em período aberto na data
        return None
    if periodo.escala_em(data) == sessao.escala and sessao.escala.atende(data):
        saindo = any(t.origem == data for t in paciente.trocas)
        origem, padrao = (Origem.TROCA_SAINDO, False) if saindo else (Origem.ALOCADO, True)
    elif any(t.destino == sessao for t in paciente.trocas):
        origem, padrao = Origem.TROCA_CHEGANDO, True
    elif sessao in paciente.extras:
        origem, padrao = Origem.EXTRA_PLANEJADA, True
    elif gravado is not None:
        origem, padrao = Origem.ACRESCENTADO, True
    else:
        return None
    return Esperado(paciente.paciente_id, origem, padrao if gravado is None else gravado, gravado is not None)


def lista_esperada(
    sessao: Sessao, candidatos: Iterable[SituacaoPaciente], excecoes: Mapping[int, bool]
) -> list[Esperado]:
    """`excecoes`: presenças já gravadas na sessão, por paciente (True = presente)."""
    itens = (_esperado(sessao, p, excecoes.get(p.paciente_id)) for p in candidatos)
    return sorted((i for i in itens if i is not None), key=lambda i: i.paciente_id)
