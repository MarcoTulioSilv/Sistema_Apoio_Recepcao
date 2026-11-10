"""Agendador do worker (AD-12, DDS §13.1): APScheduler no fuso da clínica, um gatilho por job do catálogo.

Uma instância de cada job por vez; horário perdido com o worker no ar é agrupado numa execução só; o que perdeu o
horário com o worker parado roda na partida, quando o catálogo manda (DD-08). A trava no banco garante o mesmo com
duas instâncias do worker (DD-61).
"""

from __future__ import annotations

import logging

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.base import BaseTrigger
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from sar.modulo_09_agendamento import regras
from sar.modulo_09_agendamento.contrato import Agenda, Diaria, Domingo, Intervalo, Job
from sar.modulo_09_agendamento.servicos import ServicoAgendamento
from sar.nucleo.contexto import Contexto
from sar.nucleo.logs import campos_do_erro, iniciar_requisicao
from sar.nucleo.portas import Relogio

log = logging.getLogger(__name__)
TOLERANCIA_ATRASO = 600  # segundos: o worker ocupado alguns minutos não perde a execução


def gatilho(agenda: Agenda) -> BaseTrigger | None:
    """None para o que roda fora do worker (Externa)."""
    if isinstance(agenda, Intervalo):
        return IntervalTrigger(minutes=agenda.minutos, timezone=regras.FUSO)
    if isinstance(agenda, Diaria):
        return CronTrigger(hour=agenda.hora, minute=agenda.minuto, timezone=regras.FUSO)
    if isinstance(agenda, Domingo):
        # No APScheduler, dia do mês e dia da semana se somam (E): domingo entre 1 e 7 é o primeiro do mês.
        dia = "1-7" if agenda.primeiro_do_mes else "*"
        return CronTrigger(day=dia, day_of_week="sun", hour=agenda.hora, minute=agenda.minuto, timezone=regras.FUSO)
    return None


class Agendador:
    def __init__(self, servico: ServicoAgendamento, relogio: Relogio) -> None:
        self._servico = servico
        self._relogio = relogio
        self._agendador = BackgroundScheduler(
            timezone=regras.FUSO,
            job_defaults={"coalesce": True, "max_instances": 1, "misfire_grace_time": TOLERANCIA_ATRASO},
        )

    def disparar(self, job: Job) -> None:
        """O que o APScheduler chama: cada disparo tem o seu requisicao_id, nos logs e na trilha (DD-81)."""
        iniciar_requisicao()
        try:
            self._servico.rodar(job, Contexto.sistema(f"job.{job.nome}", self._relogio.agora()), None)
        except Exception as erro:  # o agendador nunca para por causa de um job
            log.error(f"job.{job.nome}.nao_executado", extra=campos_do_erro(erro))

    def iniciar(self) -> list[str]:
        """Agenda todos os jobs do worker e devolve os que rodam já, por terem perdido o horário."""
        agora = self._relogio.agora()
        sucessos = self._servico.ultimos_sucessos()
        imediatos = []
        for job in self._servico.jobs:
            trigger = gatilho(job.agenda)
            if trigger is None or job.rotina is None:
                continue
            self._agendador.add_job(self.disparar, trigger, args=[job], id=job.nome, name=job.nome)
            if regras.deve_rodar_ao_subir(job, sucessos.get(job.nome), agora):
                imediatos.append(job.nome)
        self._agendador.start()
        for nome in imediatos:  # sem gatilho, o APScheduler roda uma vez, já; a trava evita a sobreposição
            job = next(j for j in self._servico.jobs if j.nome == nome)
            self._agendador.add_job(self.disparar, args=[job], id=f"{nome}.partida", name=f"{nome}.partida")
        log.info("agendador.iniciado", extra={"resultado": f"{len(self._agendador.get_jobs())}_jobs"})
        return imediatos

    def parar(self) -> None:
        """Sem esperar a rotina em curso: a execução fica "em andamento" e a próxima continua do último cursor."""
        if self._agendador.running:
            self._agendador.shutdown(wait=False)
