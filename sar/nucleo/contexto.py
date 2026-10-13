"""Contexto da requisição (DDS §3.2): quem age, com qual perfil, de onde e quando."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from enum import Enum

from sar.nucleo.logs import novo_requisicao_id, requisicao_atual

_REQUISICAO = re.compile(r"^[0-9a-f]{32}$")


class Perfil(str, Enum):
    RECEPCAO = "recepcao"
    ADMINISTRACAO = "administracao"
    VISUALIZADOR = "visualizador"
    TI = "ti"
    ENFERMAGEM = "enfermagem"
    SISTEMA = "sistema"  # worker e linha de comando; nunca atribuído a pessoa


@dataclass(frozen=True, slots=True)
class Contexto:
    usuario_id: int | None  # None só para o contexto de sistema
    perfil: Perfil
    sessao_id: int | None
    origem: str  # endereço da estação, ou nome do job
    instante: datetime  # UTC, com fuso
    requisicao_id: str  # 32 hex; liga auditoria e log técnico da mesma requisição (DD-81)

    def __post_init__(self) -> None:
        if not _REQUISICAO.match(self.requisicao_id):
            raise ValueError("requisicao_id fora do formato (32 hexadecimais)")
        if self.instante.utcoffset() is None:
            raise ValueError("instante sem fuso")

    @classmethod
    def sistema(cls, origem: str, instante: datetime, requisicao_id: str | None = None) -> Contexto:
        """Worker e linha de comando. Sem id explícito, usa o da execução em andamento (o mesmo dos logs)
        ou gera um novo."""
        return cls(
            usuario_id=None,
            perfil=Perfil.SISTEMA,
            sessao_id=None,
            origem=origem,
            instante=instante,
            requisicao_id=requisicao_id or requisicao_atual() or novo_requisicao_id(),
        )

    @property
    def e_sistema(self) -> bool:
        return self.perfil is Perfil.SISTEMA
