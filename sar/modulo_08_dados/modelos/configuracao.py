"""Modelos do MOD-06 Configuração (DDS §10.4). Os demais (instituição, convênio, município) entram com as
funções que os usam."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import ForeignKey, String
from sqlalchemy.dialects import mysql
from sqlalchemy.orm import Mapped, mapped_column

from sar.modulo_08_dados.modelos import Base


class Parametro(Base):
    """Só o valor alterado; o padrão, os limites e o editor estão declarados no núcleo (DD-48, DD-73)."""

    __tablename__ = "parametro"

    nome: Mapped[str] = mapped_column(String(60), primary_key=True)
    valor: Mapped[str] = mapped_column(String(200))
    alterado_em: Mapped[datetime] = mapped_column(mysql.DATETIME(fsp=6))
    alterado_por: Mapped[int] = mapped_column(
        mysql.BIGINT(unsigned=True), ForeignKey("usuario.id", name="fk_parametro__alterado_por")
    )
