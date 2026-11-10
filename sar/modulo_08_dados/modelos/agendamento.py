"""Modelo do MOD-09 Agendamento (DDS §13.4). Espelha a 0001 e a 0008 (cursor das rotinas que param no horário)."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Enum, Index, String
from sqlalchemy.dialects import mysql
from sqlalchemy.orm import Mapped, mapped_column

from sar.modulo_08_dados.modelos import Base

INSTANTE = mysql.DATETIME(fsp=6)


class JobExecucao(Base):
    """Uma linha por execução, sem dado pessoal (DD-61, RNF-624). `itens` é a quantidade processada; no job de disco,
    o percentual de ocupação medido (DD-111). `cursor` é onde a rotina parou no limite de horário (DD-64)."""

    __tablename__ = "job_execucao"
    __table_args__ = (Index("ix_job_execucao__job_inicio", "job", "inicio"),)

    id: Mapped[int] = mapped_column(mysql.BIGINT(unsigned=True), primary_key=True, autoincrement=True)
    job: Mapped[str] = mapped_column(String(60))
    inicio: Mapped[datetime] = mapped_column(INSTANTE)
    fim: Mapped[datetime | None] = mapped_column(INSTANTE)
    resultado: Mapped[str] = mapped_column(
        Enum("em_andamento", "sucesso", "falha", "sem_trabalho", name="resultado_job")
    )
    itens: Mapped[int | None] = mapped_column(mysql.INTEGER(unsigned=True))
    resumo_erro: Mapped[str | None] = mapped_column(String(300))
    cursor: Mapped[str | None] = mapped_column(String(64))
