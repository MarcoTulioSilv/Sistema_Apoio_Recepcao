"""Regras puras do MOD-09 (DDS §13, DD-08, DD-61, DD-64): atraso, horário perdido, janela e limite da madrugada.

Recebem o instante; nenhuma lê o relógio.
"""

from __future__ import annotations

from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

from sar.modulo_09_agendamento.contrato import Agenda, Diaria, Domingo, Intervalo, Job

FUSO = ZoneInfo("America/Sao_Paulo")
LIMITE_PESADAS = time(4, 30)  # DD-64: nada pesado alcança a janela das 05:00
INICIO_JANELA, FIM_JANELA = time(5, 0), time(20, 0)  # DEC-68, de segunda a sábado
DIAS_DA_SEMANA = ("segunda", "terça", "quarta", "quinta", "sexta", "sábado", "domingo")


def periodo(agenda: Agenda) -> timedelta | None:
    """O intervalo nominal entre duas execuções agendadas."""
    if isinstance(agenda, Intervalo):
        return timedelta(minutes=agenda.minutos)
    if isinstance(agenda, Diaria):
        return timedelta(days=1)
    if isinstance(agenda, Domingo):
        return timedelta(days=28 if agenda.primeiro_do_mes else 7)
    return agenda.periodo


def quando(agenda: Agenda) -> str:
    """Como a §13.1 escreve a agenda."""
    if isinstance(agenda, Intervalo):
        return "A cada hora" if agenda.minutos == 60 else f"A cada {agenda.minutos} min"
    if isinstance(agenda, Diaria):
        return f"Diário, {agenda.hora:02d}:{agenda.minuto:02d}"
    if isinstance(agenda, Domingo):
        dia = "Primeiro domingo do mês" if agenda.primeiro_do_mes else "Domingo"
        return f"{dia}, {agenda.hora:02d}:{agenda.minuto:02d}"
    return agenda.descricao


def em_janela_de_operacao(agora: datetime) -> bool:
    local = agora.astimezone(FUSO)
    return local.weekday() < 6 and INICIO_JANELA <= local.time() < FIM_JANELA


def atrasado_desde(
    intervalo_maximo: timedelta, ultimo_sucesso: datetime | None, agora: datetime, implantacao: datetime | None
) -> datetime | None:
    """Desde quando o job está atrasado (pendência 17), ou None. Sem nenhum sucesso, o prazo conta da implantação:
    antes dela, nenhum job está atrasado (DD-91)."""
    referencia = ultimo_sucesso if ultimo_sucesso is not None else implantacao
    if referencia is None:
        return None
    vence = referencia + intervalo_maximo
    return vence if agora > vence else None


def deve_rodar_ao_subir(job: Job, ultimo_sucesso: datetime | None, agora: datetime) -> bool:
    """DD-08: o job que roda ao subir e perdeu o horário executa na partida do worker; a verificação da cadeia, só
    fora da janela de operação."""
    if not job.roda_ao_subir or job.rotina is None:
        return False
    if job.fora_da_janela and em_janela_de_operacao(agora):
        return False
    nominal = periodo(job.agenda)
    return ultimo_sucesso is None or nominal is None or agora - ultimo_sucesso >= nominal


def segundos_ate_o_limite(agora: datetime) -> float:
    """Até as próximas 04:30 da clínica (DD-64); as rotinas com cursor param ali e continuam na próxima vez."""
    local = agora.astimezone(FUSO)
    limite = datetime.combine(local.date(), LIMITE_PESADAS, FUSO)
    if limite <= local:
        limite += timedelta(days=1)
    return (limite - local).total_seconds()
