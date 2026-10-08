"""Contrato do MOD-06 Configuração (DDS §10.3): a única parte importável de fora do módulo. A leitura de
parâmetro pelos outros módulos é pela porta LeitorParametros do núcleo (DD-73), não por aqui."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Protocol

from sar.nucleo.contexto import Contexto, Perfil

Valor = int | bool | date | None


@dataclass(frozen=True, slots=True)
class ParametroVigente:
    nome: str
    unidade: str
    valor: Valor
    padrao: Valor
    minimo: int | None
    maximo: int | None
    editor: Perfil
    imutavel_apos_uso: bool
    alterado_em: datetime | None  # None: nunca alterado, vale o padrão
    alterado_por: int | None


class ConfiguracaoService(Protocol):
    def listar_parametros(self, contexto: Contexto) -> list[ParametroVigente]: ...

    def alterar_parametro(self, contexto: Contexto, nome: str, valor: Valor) -> None:
        """Administração altera os operacionais; TI, os técnicos (§4.6). RegraViolada se o valor estiver fora
        dos limites ou do tipo, ou se o parâmetro for imutável e já tiver sido usado (DD-51). Auditada com o
        valor antes e depois."""
        ...
