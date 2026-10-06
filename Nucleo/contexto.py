"""Contexto da requisição (DDS §3.2): quem age, com qual perfil, de onde e quando."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum


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

    @classmethod
    def sistema(cls, origem: str, instante: datetime) -> Contexto:
        return cls(usuario_id=None, perfil=Perfil.SISTEMA, sessao_id=None, origem=origem, instante=instante)

    @property
    def e_sistema(self) -> bool:
        return self.perfil is Perfil.SISTEMA
