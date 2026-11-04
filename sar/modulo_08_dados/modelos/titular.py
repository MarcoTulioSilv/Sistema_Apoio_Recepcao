"""Modelo do MOD-11 Atendimento ao titular (DDS §15). Espelha a 0001; o prazo é derivado, não guardado (DD-18)."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Enum, ForeignKey, Index, String, Text
from sqlalchemy.dialects import mysql
from sqlalchemy.orm import Mapped, mapped_column

from sar.modulo_08_dados.modelos import Base

BIGINT = mysql.BIGINT(unsigned=True)
INSTANTE = mysql.DATETIME(fsp=6)


class RequisicaoTitular(Base):
    __tablename__ = "requisicao_titular"
    __table_args__ = (Index("ix_requisicao_titular__situacao", "situacao", "recebida_em"),)

    id: Mapped[int] = mapped_column(BIGINT, primary_key=True, autoincrement=True)
    paciente_id: Mapped[int] = mapped_column(
        BIGINT, ForeignKey("paciente.id", name="fk_requisicao_titular__paciente_id")
    )
    tipo: Mapped[str] = mapped_column(
        Enum("confirmacao_acesso", "correcao", "informacao", "eliminacao", "outros", name="tipo_requisicao")
    )
    canal: Mapped[str] = mapped_column(String(40))
    recebida_em: Mapped[datetime] = mapped_column(INSTANTE)
    situacao: Mapped[str] = mapped_column(Enum("aberta", "atendida", "negada", name="situacao_requisicao"))
    desfecho: Mapped[str | None] = mapped_column(Text)
    atendida_em: Mapped[datetime | None] = mapped_column(INSTANTE)
    atendente_id: Mapped[int | None] = mapped_column(
        BIGINT, ForeignKey("usuario.id", name="fk_requisicao_titular__atendente_id")
    )
