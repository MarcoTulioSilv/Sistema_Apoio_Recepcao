"""Pendências do MOD-09 (DDS §11.1, linhas 17 e 19; DD-54). Só o TI, só identificadores internos (RNF-625)."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime

from sar.modulo_08_dados.interfaces.agendamento import RepositorioAgendamento
from sar.modulo_09_agendamento import regras
from sar.modulo_09_agendamento.catalogo import CONSUMIDOR_FILA, OCUPACAO_DISCO
from sar.modulo_09_agendamento.contrato import Job, Resultado
from sar.modulo_09_agendamento.servicos import fila_parada, implantacao
from sar.nucleo.contexto import Contexto, Perfil
from sar.nucleo.parametros import LeitorParametros
from sar.nucleo.portas import FontePendencia, ItemPendencia, Prioridade
from sar.nucleo.uow import UnidadeDeTrabalho

DESTINO = "/agendamento"


def _local(instante: datetime) -> str:
    return f"{instante.astimezone(regras.FUSO):%d/%m/%Y %H:%M}"


class _FonteDoTi:
    codigo: str

    def contar(self, uow: UnidadeDeTrabalho, contexto: Contexto) -> int:
        return len(self.listar(uow, contexto))

    def listar(self, uow: UnidadeDeTrabalho, contexto: Contexto) -> list[ItemPendencia]:
        return self._itens(uow, contexto) if contexto.perfil is Perfil.TI else []

    def listar_por_pacientes(
        self, uow: UnidadeDeTrabalho, contexto: Contexto, paciente_ids: Sequence[int]
    ) -> list[ItemPendencia]:
        return []

    def _itens(self, uow: UnidadeDeTrabalho, contexto: Contexto) -> list[ItemPendencia]:
        raise NotImplementedError


class FonteJobAtrasado(_FonteDoTi):
    """Linha 17 (R-38, DD-61): job sem execução bem-sucedida dentro do intervalo máximo, inclusive o backup e a cópia
    para o pen drive, registrados pelos scripts do servidor (DD-62). O consumidor da fila, que é um laço e não um
    job, conta como parado quando há ingestão recebida esperando mais que o intervalo dele."""

    codigo = "job_atrasado"

    def __init__(self, jobs: Sequence[Job], parametros: LeitorParametros) -> None:
        self._jobs = tuple(jobs)
        self._parametros = parametros

    def _itens(self, uow: UnidadeDeTrabalho, contexto: Contexto) -> list[ItemPendencia]:
        agora, inicio = contexto.instante, implantacao(self._parametros)
        sucessos = uow.repositorio(RepositorioAgendamento).ultimos_sucessos()
        itens = []
        for job in self._jobs:
            if job.nome == CONSUMIDOR_FILA:
                itens.extend(self._fila(uow, job, agora))
                continue
            ultimo = sucessos.get(job.nome)
            desde = regras.atrasado_desde(job.intervalo_maximo, ultimo, agora, inicio)
            if desde is None:
                continue
            quando = f"último sucesso em {_local(ultimo)}" if ultimo else "nenhuma execução bem-sucedida"
            itens.append(ItemPendencia(self.codigo, Prioridade.URGENCIA, desde, f"{job.rotulo}: {quando}", DESTINO,
                                       identificador_interno=job.nome))  # fmt: skip
        return itens

    def _fila(self, uow: UnidadeDeTrabalho, job: Job, agora: datetime) -> list[ItemPendencia]:
        parada = fila_parada(uow, job, agora)
        if parada is None:
            return []
        desde, quantas = parada
        descricao = f"{job.rotulo}: {quantas} digitalização(ões) esperando há mais de 5 min"
        return [ItemPendencia(self.codigo, Prioridade.URGENCIA, desde, descricao, DESTINO,
                              identificador_interno=job.nome)]  # fmt: skip


class FonteDiscoAcimaDoLimite(_FonteDoTi):
    """Linha 19 (RNF-621, DD-111): a última medição do job de disco passou do alarme do parâmetro."""

    codigo = "disco_acima_do_limite"

    def __init__(self, parametros: LeitorParametros) -> None:
        self._parametros = parametros

    def _itens(self, uow: UnidadeDeTrabalho, contexto: Contexto) -> list[ItemPendencia]:
        medicao = uow.repositorio(RepositorioAgendamento).ultima(OCUPACAO_DISCO, Resultado.SUCESSO.value)
        alarme = self._parametros.valor("disco_alarme_ocupacao")
        if medicao is None or medicao.itens is None or not isinstance(alarme, int):
            return []
        if not acima_do_alarme(medicao.itens, alarme):
            return []
        descricao = (
            f"Disco com {medicao.itens}% ocupado (alarme a partir de {alarme}%), medido em {_local(medicao.inicio)}"
        )
        return [ItemPendencia(self.codigo, Prioridade.ALTA, medicao.inicio, descricao, DESTINO,
                              identificador_interno=OCUPACAO_DISCO)]  # fmt: skip


def acima_do_alarme(percentual: int, alarme: int) -> bool:
    """O alarme dispara a partir do percentual do parâmetro, inclusive (DD-111)."""
    return percentual >= alarme


def fontes(jobs: Sequence[Job], parametros: LeitorParametros) -> tuple[FontePendencia, ...]:
    return (FonteJobAtrasado(jobs, parametros), FonteDiscoAcimaDoLimite(parametros))
