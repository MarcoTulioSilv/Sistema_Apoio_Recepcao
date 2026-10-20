"""Modelos do MOD-03 Operação (DDS §7.9). Espelham a 0001; um teste de integração confere contra o banco
migrado. Sem relacionamentos: o repositório carrega o agregado explicitamente (DD-12)."""

from __future__ import annotations

from datetime import date, datetime, time

from sqlalchemy import CheckConstraint, Computed, Date, Enum, ForeignKey, Index, String, Time, UniqueConstraint
from sqlalchemy.dialects import mysql
from sqlalchemy.orm import Mapped, mapped_column

from sar.modulo_08_dados.modelos import Base

BIGINT = mysql.BIGINT(unsigned=True)
TINYINT = mysql.TINYINT(unsigned=True)
INSTANTE = mysql.DATETIME(fsp=6)
COMPETENCIA = "competencia REGEXP '^[0-9]{4}-(0[1-9]|1[0-2])$'"


def _ascii(tamanho: int) -> mysql.CHAR:
    return mysql.CHAR(tamanho, charset="ascii", collation="ascii_bin")


def _fk(tabela: str, coluna: str, alvo: str) -> ForeignKey:
    return ForeignKey(alvo, name=f"fk_{tabela}__{coluna}")


def _ativa() -> Mapped[int | None]:
    """1 enquanto não cancelada, NULL depois: com o índice único, só vale entre as ativas (§7.9)."""
    return mapped_column(TINYINT, Computed("IF(cancelada_em IS NULL, 1, NULL)", persisted=True))


class Escala(Base):
    """Tabela fixa, carregada pela 0002 e nunca alterada pela aplicação (DEC-52)."""

    __tablename__ = "escala"
    __table_args__ = (UniqueConstraint("codigo", name="uq_escala__codigo"),)

    id: Mapped[int] = mapped_column(TINYINT, primary_key=True, autoincrement=False)
    codigo: Mapped[str] = mapped_column(_ascii(5))
    turno: Mapped[int] = mapped_column(TINYINT)
    dias: Mapped[str] = mapped_column(String(20))
    hora_inicio: Mapped[time] = mapped_column(Time)
    hora_fim: Mapped[time] = mapped_column(Time)


class Alocacao(Base):
    """Só com início; escala nula = sem alocação a partir dessa data (DD-27)."""

    __tablename__ = "alocacao"
    __table_args__ = (UniqueConstraint("periodo_id", "vigencia_inicio", name="uq_alocacao__inicio"),)

    id: Mapped[int] = mapped_column(BIGINT, primary_key=True, autoincrement=True)
    periodo_id: Mapped[int] = mapped_column(BIGINT, _fk("alocacao", "periodo_id", "periodo_tratamento.id"))
    escala_id: Mapped[int | None] = mapped_column(TINYINT, _fk("alocacao", "escala_id", "escala.id"))
    vigencia_inicio: Mapped[date] = mapped_column(Date)


class TrocaPontual(Base):
    __tablename__ = "troca_pontual"
    __table_args__ = (
        UniqueConstraint("paciente_id", "data_origem", "ativa", name="uq_troca_pontual__origem"),
        CheckConstraint(
            "EXTRACT(YEAR_MONTH FROM data_origem) = EXTRACT(YEAR_MONTH FROM data_destino)", name="mesmo_mes"
        ),  # P-11
    )

    id: Mapped[int] = mapped_column(BIGINT, primary_key=True, autoincrement=True)
    paciente_id: Mapped[int] = mapped_column(BIGINT, _fk("troca_pontual", "paciente_id", "paciente.id"))
    data_origem: Mapped[date] = mapped_column(Date)
    data_destino: Mapped[date] = mapped_column(Date)
    escala_destino_id: Mapped[int] = mapped_column(TINYINT, _fk("troca_pontual", "escala_destino_id", "escala.id"))
    documento_id: Mapped[bytes | None] = mapped_column(
        mysql.BINARY(16), _fk("troca_pontual", "documento_id", "documento.id")
    )
    cancelada_em: Mapped[datetime | None] = mapped_column(INSTANTE)
    cancelada_motivo: Mapped[str | None] = mapped_column(String(300))
    ativa: Mapped[int | None] = _ativa()


class ExtraPlanejada(Base):
    __tablename__ = "extra_planejada"
    __table_args__ = (UniqueConstraint("paciente_id", "data", "escala_id", "ativa", name="uq_extra_planejada__sessao"),)

    id: Mapped[int] = mapped_column(BIGINT, primary_key=True, autoincrement=True)
    paciente_id: Mapped[int] = mapped_column(BIGINT, _fk("extra_planejada", "paciente_id", "paciente.id"))
    data: Mapped[date] = mapped_column(Date)
    escala_id: Mapped[int] = mapped_column(TINYINT, _fk("extra_planejada", "escala_id", "escala.id"))
    cancelada_em: Mapped[datetime | None] = mapped_column(INSTANTE)
    cancelada_motivo: Mapped[str | None] = mapped_column(String(300))
    ativa: Mapped[int | None] = _ativa()


class TermoExtra(Base):
    """Um termo de extra (DOC-07) por paciente e competência (RF-805)."""

    __tablename__ = "termo_extra"
    __table_args__ = (
        UniqueConstraint("paciente_id", "competencia", name="uq_termo_extra__competencia"),
        CheckConstraint(COMPETENCIA, name="competencia"),
    )

    id: Mapped[int] = mapped_column(BIGINT, primary_key=True, autoincrement=True)
    paciente_id: Mapped[int] = mapped_column(BIGINT, _fk("termo_extra", "paciente_id", "paciente.id"))
    competencia: Mapped[str] = mapped_column(_ascii(7))
    documento_id: Mapped[bytes] = mapped_column(mysql.BINARY(16), _fk("termo_extra", "documento_id", "documento.id"))


class SessaoTurno(Base):
    """Gravada só na primeira marcação ou na confirmação (DD-23)."""

    __tablename__ = "sessao_turno"
    __table_args__ = (
        UniqueConstraint("data", "escala_id", name="uq_sessao_turno__data_escala"),
        CheckConstraint("(confirmada_em IS NULL) = (confirmada_por IS NULL)", name="confirmacao"),
        CheckConstraint("nao_realizada_motivo IS NULL OR confirmada_em IS NOT NULL", name="nao_realizada"),
    )

    id: Mapped[int] = mapped_column(BIGINT, primary_key=True, autoincrement=True)
    data: Mapped[date] = mapped_column(Date)
    escala_id: Mapped[int] = mapped_column(TINYINT, _fk("sessao_turno", "escala_id", "escala.id"))
    confirmada_em: Mapped[datetime | None] = mapped_column(INSTANTE)
    confirmada_por: Mapped[int | None] = mapped_column(BIGINT, _fk("sessao_turno", "confirmada_por", "usuario.id"))
    nao_realizada_motivo: Mapped[str | None] = mapped_column(String(300))  # P-12
    versao: Mapped[int] = mapped_column(mysql.INTEGER(unsigned=True), server_default="1")


class Presenca(Base):
    __tablename__ = "presenca"
    __table_args__ = (
        UniqueConstraint("sessao_id", "paciente_id", name="uq_presenca__sessao_paciente"),
        Index("ix_presenca__paciente", "paciente_id"),
    )

    id: Mapped[int] = mapped_column(BIGINT, primary_key=True, autoincrement=True)
    sessao_id: Mapped[int] = mapped_column(BIGINT, _fk("presenca", "sessao_id", "sessao_turno.id"))
    paciente_id: Mapped[int] = mapped_column(BIGINT, _fk("presenca", "paciente_id", "paciente.id"))
    situacao: Mapped[str] = mapped_column(Enum("presente", "ausente", name="situacao_presenca"))


class LigacaoManual(Base):
    """Par ausência–presença escolhido pela recepção (DD-25); mesmo paciente e mês, conferidos no serviço."""

    __tablename__ = "ligacao_manual"
    __table_args__ = (
        UniqueConstraint("ausencia_id", name="uq_ligacao_manual__ausencia"),
        UniqueConstraint("presenca_id", name="uq_ligacao_manual__presenca"),
        CheckConstraint("ausencia_id <> presenca_id", name="distintas"),
    )

    id: Mapped[int] = mapped_column(BIGINT, primary_key=True, autoincrement=True)
    ausencia_id: Mapped[int] = mapped_column(BIGINT, _fk("ligacao_manual", "ausencia_id", "presenca.id"))
    presenca_id: Mapped[int] = mapped_column(BIGINT, _fk("ligacao_manual", "presenca_id", "presenca.id"))
    criada_por: Mapped[int] = mapped_column(BIGINT, _fk("ligacao_manual", "criada_por", "usuario.id"))
    criada_em: Mapped[datetime] = mapped_column(INSTANTE)


class CienciaEnfermagem(Base):
    __tablename__ = "ciencia_enfermagem"

    presenca_id: Mapped[int] = mapped_column(
        BIGINT, _fk("ciencia_enfermagem", "presenca_id", "presenca.id"), primary_key=True, autoincrement=False
    )
    registrada_em: Mapped[datetime] = mapped_column(INSTANTE)
    registrada_por: Mapped[int] = mapped_column(BIGINT, _fk("ciencia_enfermagem", "registrada_por", "usuario.id"))


class MesAlterado(Base):
    """Só inserção (RF-915): a marca de alteração depois do fechamento (DD-26)."""

    __tablename__ = "mes_alterado"
    __table_args__ = (
        CheckConstraint(COMPETENCIA, name="competencia"),
        Index("ix_mes_alterado__competencia", "competencia"),
    )

    id: Mapped[int] = mapped_column(BIGINT, primary_key=True, autoincrement=True)
    competencia: Mapped[str] = mapped_column(_ascii(7))
    instante: Mapped[datetime] = mapped_column(INSTANTE)
    responsavel_id: Mapped[int] = mapped_column(BIGINT, _fk("mes_alterado", "responsavel_id", "usuario.id"))
    autorizador_id: Mapped[int] = mapped_column(BIGINT, _fk("mes_alterado", "autorizador_id", "usuario.id"))
    motivo: Mapped[str] = mapped_column(String(500))
    solicitacao_id: Mapped[bytes | None] = mapped_column(
        mysql.BINARY(16), _fk("mes_alterado", "solicitacao_id", "solicitacao_autorizacao.id")
    )
