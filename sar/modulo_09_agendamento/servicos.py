"""Execução e registro dos jobs (DDS §13, DD-61, DD-62, DD-64, DD-112).

Cada execução obtém a trava do próprio job (outra instância do worker não roda o mesmo job em paralelo) e, se for
pesada, a trava compartilhada das rotinas da madrugada, esperando a anterior até o limite das 04:30. Grava início,
fim, resultado e itens em `job_execucao`; a falha grava só o nome do erro (RNF-624).
"""

from __future__ import annotations

import logging
import time as relogio_monotonico
from collections.abc import Sequence
from contextlib import nullcontext
from datetime import date, datetime, time

from sar.modulo_01_acesso.contrato import AuditService, PermissionGuard
from sar.modulo_08_dados.interfaces.agendamento import ExecucaoGravada, RepositorioAgendamento, Trava
from sar.modulo_08_dados.interfaces.documentos import RepositorioDocumentos
from sar.modulo_09_agendamento import regras
from sar.modulo_09_agendamento.catalogo import CONSUMIDOR_FILA, REGISTRAVEIS
from sar.modulo_09_agendamento.contrato import (
    Execucao,
    Job,
    JobDesconhecido,
    JobEmAndamento,
    Resultado,
    ResultadoJob,
    Rotina,
    SituacaoJob,
)
from sar.nucleo.contexto import Contexto
from sar.nucleo.erros import AcessoNegado, RegraViolada
from sar.nucleo.logs import campos_do_erro
from sar.nucleo.parametros import LeitorParametros
from sar.nucleo.portas import Relogio
from sar.nucleo.uow import ExecutorDeOperacao, UnidadeDeTrabalho

log = logging.getLogger(__name__)
GUARDA = PermissionGuard()
TRAVA_PESADAS = "job:pesadas"
EXECUTAR_AGORA, REGISTRAR_EXTERNO = "agendamento.job.executar_agora", "agendamento.backup.registrar"


def execucao(gravada: ExecucaoGravada) -> Execucao:
    return Execucao(gravada.id, gravada.job, gravada.inicio, gravada.fim, Resultado(gravada.resultado), gravada.itens,
                    gravada.resumo_erro, gravada.cursor is not None)  # fmt: skip


def fila_parada(uow: UnidadeDeTrabalho, job: Job, agora: datetime) -> tuple[datetime, int] | None:
    """O consumidor da fila é um laço, não um job (DD-63): está parado quando há digitalização recebida esperando
    mais que o intervalo máximo dele. Devolve desde quando e quantas, ou None."""
    paradas = uow.repositorio(RepositorioDocumentos).criadas_antes(["recebida"], agora - job.intervalo_maximo)
    return (paradas[0].criada_em + job.intervalo_maximo, len(paradas)) if paradas else None


def implantacao(parametros: LeitorParametros) -> datetime | None:
    valor = parametros.valor("data_implantacao")
    return datetime.combine(valor, time(), regras.FUSO) if isinstance(valor, date) else None


class ServicoAgendamento:
    def __init__(
        self,
        executar: ExecutorDeOperacao,
        auditoria: AuditService,
        parametros: LeitorParametros,
        trava: Trava,
        jobs: Sequence[Job],
        relogio: Relogio,
    ) -> None:
        self._executar = executar
        self._auditoria = auditoria
        self._parametros = parametros
        self._trava = trava
        self._relogio = relogio
        self.jobs = tuple(jobs)
        self._por_nome = {job.nome: job for job in self.jobs}

    def job(self, nome: str) -> Job:
        try:
            return self._por_nome[nome]
        except KeyError:
            raise JobDesconhecido(nome) from None

    # ---------------------------------------------------------------- execução
    def rodar(self, job: Job, contexto: Contexto, segundos: float | None, manual: bool = False) -> Execucao | None:
        """None se outra instância já roda o job. Agendada, a pesada para no limite das 04:30 (DD-64)."""
        rotina = job.rotina
        if rotina is None:
            raise RegraViolada("agendamento.job_externo")
        with self._trava.obter(f"job:{job.nome}", 0) as obtida:
            if not obtida:
                log.warning(f"job.{job.nome}.trava_ocupada")
                return None
            if job.pesado and segundos is None:  # agendada: para às 04:30 e continua na próxima (DD-64)
                segundos = regras.segundos_ate_o_limite(contexto.instante)
            compartilhada = self._trava.obter(TRAVA_PESADAS, segundos or 0) if job.pesado else nullcontext(True)
            with compartilhada as pesada:
                return self._rodar(job, rotina, contexto, segundos, manual, pesada)

    def _rodar(
        self, job: Job, rotina: Rotina, contexto: Contexto, segundos: float | None, manual: bool, pesada: bool
    ) -> Execucao:
        cursor = self._executar(lambda uow: self._cursor(uow, job.nome))

        def abrir(uow: UnidadeDeTrabalho) -> int:
            execucao_id = uow.repositorio(RepositorioAgendamento).abrir(job.nome, contexto.instante)
            if manual:  # DD-112: a execução manual pela linha de comando fica na trilha
                self._auditoria.registrar(uow, contexto, EXECUTAR_AGORA, "job_execucao", str(execucao_id),
                                          {"job": (None, job.nome)})  # fmt: skip
            return execucao_id

        execucao_id = self._executar(abrir)
        partida = relogio_monotonico.monotonic()
        try:
            if not pesada:  # a rotina anterior da série passou do limite (DD-64)
                raise JobEmAndamento(TRAVA_PESADAS)
            resultado: ResultadoJob = rotina(contexto, cursor, segundos)
        except Exception as erro:
            log.error(f"job.{job.nome}.falhou", extra=campos_do_erro(erro))
            return self._fechar(execucao_id, Resultado.FALHA, None, type(erro).__name__, None, partida)
        estado = Resultado.SEM_TRABALHO if resultado.sem_trabalho else Resultado.SUCESSO
        return self._fechar(execucao_id, estado, resultado.itens, None, resultado.cursor, partida)

    def _fechar(self, execucao_id: int, resultado: Resultado, itens: int | None, erro: str | None, cursor: str | None,
                partida: float) -> Execucao:  # fmt: skip
        fim = self._relogio.agora()  # o instante da conclusão, não o do contexto da partida

        def fechar(uow: UnidadeDeTrabalho) -> ExecucaoGravada:
            repo = uow.repositorio(RepositorioAgendamento)
            repo.fechar(execucao_id, fim, resultado.value, itens, erro, cursor)
            return repo.por_id(execucao_id)

        gravada = self._executar(fechar)
        duracao = int((relogio_monotonico.monotonic() - partida) * 1000)
        log.info(f"job.{gravada.job}.concluido", extra={"resultado": resultado.value, "duracao_ms": duracao})
        return execucao(gravada)

    @staticmethod
    def _cursor(uow: UnidadeDeTrabalho, nome: str) -> str | None:
        """Continua do ponto em que a última execução bem-sucedida parou; depois de uma passada completa, recomeça."""
        ultima = uow.repositorio(RepositorioAgendamento).ultima(nome, Resultado.SUCESSO.value)
        return ultima.cursor if ultima is not None else None

    # ---------------------------------------------------------------- linha de comando (DD-112, DD-62)
    def executar(self, contexto: Contexto, nome: str, minutos: float | None = None) -> Execucao:
        GUARDA.exigir(contexto, EXECUTAR_AGORA)
        job = self.job(nome)
        if not job.manual_permitida or job.rotina is None:
            raise AcessoNegado()
        feita = self.rodar(job, contexto, minutos * 60 if minutos is not None else None, manual=True)
        if feita is None:
            raise JobEmAndamento(nome)
        return feita

    def registrar_externo(
        self, contexto: Contexto, nome: str, resultado: Resultado, inicio: datetime, fim: datetime,
        itens: int | None = None,
    ) -> Execucao:  # fmt: skip
        GUARDA.exigir(contexto, REGISTRAR_EXTERNO)
        if nome not in REGISTRAVEIS:
            raise JobDesconhecido(nome)
        if resultado is Resultado.EM_ANDAMENTO or fim < inicio:
            raise RegraViolada("agendamento.registro_invalido")

        def operacao(uow: UnidadeDeTrabalho) -> ExecucaoGravada:
            repo = uow.repositorio(RepositorioAgendamento)
            execucao_id = repo.registrar(nome, inicio, fim, resultado.value, itens, None)
            self._auditoria.registrar(uow, contexto, REGISTRAR_EXTERNO, "job_execucao", str(execucao_id),
                                      {"job": (None, nome), "resultado": (None, resultado.value)})  # fmt: skip
            return repo.por_id(execucao_id)

        return execucao(self._executar(operacao))

    # ---------------------------------------------------------------- consulta (TI, só leitura)
    def ultimos_sucessos(self) -> dict[str, datetime]:
        """Para o agendador decidir o que roda na partida (DD-08); sem verificação de perfil: é o próprio worker."""
        return self._executar(lambda uow: uow.repositorio(RepositorioAgendamento).ultimos_sucessos())

    def situacao(self, contexto: Contexto) -> list[SituacaoJob]:
        GUARDA.exigir(contexto, "agendamento.execucoes.ver")
        return self._situacao(contexto.instante)

    def situacao_do_sistema(self, agora: datetime) -> list[SituacaoJob]:
        """A mesma consulta, para o `sar job listar` no servidor: só nomes e instantes, sem dado de paciente."""
        return self._situacao(agora)

    def _situacao(self, agora: datetime) -> list[SituacaoJob]:
        inicio = implantacao(self._parametros)

        def operacao(uow: UnidadeDeTrabalho) -> tuple[dict[str, datetime], dict[str, ExecucaoGravada | None], bool]:
            repo = uow.repositorio(RepositorioAgendamento)
            fila = next((j for j in self.jobs if j.nome == CONSUMIDOR_FILA), None)
            parada = fila is not None and fila_parada(uow, fila, agora) is not None
            return repo.ultimos_sucessos(), {job.nome: repo.ultima(job.nome) for job in self.jobs}, parada

        sucessos, ultimas, fila_parou = self._executar(operacao)
        saida = []
        for job in self.jobs:
            ultima = ultimas[job.nome]
            if job.nome == CONSUMIDOR_FILA:
                atrasado = fila_parou
            else:
                atrasado = (
                    regras.atrasado_desde(job.intervalo_maximo, sucessos.get(job.nome), agora, inicio) is not None
                )
            saida.append(SituacaoJob(job.nome, job.rotulo, job.modulo, regras.quando(job.agenda), job.intervalo_maximo,
                                     sucessos.get(job.nome), execucao(ultima) if ultima else None,
                                     atrasado))  # fmt: skip
        return saida

    def execucoes(self, contexto: Contexto, job: str | None = None, limite: int = 50) -> list[Execucao]:
        GUARDA.exigir(contexto, "agendamento.execucoes.ver")
        if job is not None:
            self.job(job)
        return self._executar(
            lambda uow: [execucao(e) for e in uow.repositorio(RepositorioAgendamento).recentes(limite, job)]
        )
