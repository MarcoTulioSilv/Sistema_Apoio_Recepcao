"""Relatórios (DDS §10). Por ora, só os aniversariantes do dia (RF-909)."""

from __future__ import annotations

from datetime import date

from sar.modulo_01_acesso.contrato import PermissionGuard
from sar.modulo_02_cadastro.contrato import LeituraCadastro
from sar.nucleo.contexto import Contexto
from sar.nucleo.uow import ExecutorDeOperacao

GUARDA = PermissionGuard()


class ServicoRelatorios:
    def __init__(self, executar: ExecutorDeOperacao, leitura: LeituraCadastro) -> None:
        self._executar = executar
        self._leitura = leitura

    def aniversariantes(self, contexto: Contexto, data: date) -> list[str]:
        GUARDA.exigir(contexto, "relatorio.aniversariantes.ver")
        return [i.nome for i in self._executar(lambda uow: self._leitura.aniversariantes(uow, data))]
