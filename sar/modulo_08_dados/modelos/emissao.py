"""Modelos do MOD-05 Emissão (DDS §9.5). Espelham a 0001; um teste de integração confere contra o banco migrado."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Computed, ForeignKey, Index, String, UniqueConstraint
from sqlalchemy.dialects import mysql
from sqlalchemy.orm import Mapped, mapped_column

from sar.modulo_08_dados.modelos import Base

BIGINT = mysql.BIGINT(unsigned=True)
INSTANTE = mysql.DATETIME(fsp=6)


class ModeloDocumento(Base):
    """Versões enviadas pela administração (DD-42); a versão 0 é o modelo embutido e não tem linha (DD-103). Sem
    dado de paciente."""

    __tablename__ = "modelo_documento"
    __table_args__ = (
        UniqueConstraint("codigo", "versao", name="uq_modelo_documento__versao"),
        UniqueConstraint("codigo", "ativo_marcador", name="uq_modelo_documento__um_ativo"),
    )

    id: Mapped[int] = mapped_column(BIGINT, primary_key=True, autoincrement=True)
    codigo: Mapped[str] = mapped_column(String(20))
    versao: Mapped[int] = mapped_column(mysql.INTEGER(unsigned=True))
    arquivo: Mapped[bytes] = mapped_column(mysql.MEDIUMBLOB, deferred=True)
    hash_sha256: Mapped[str] = mapped_column(mysql.CHAR(64, charset="ascii", collation="ascii_bin"))
    enviado_em: Mapped[datetime] = mapped_column(INSTANTE)
    enviado_por: Mapped[int] = mapped_column(BIGINT, ForeignKey("usuario.id", name="fk_modelo_documento__enviado_por"))
    ativo: Mapped[bool] = mapped_column(server_default="0")
    ativado_em: Mapped[datetime | None] = mapped_column(INSTANTE)
    ativado_por: Mapped[int | None] = mapped_column(
        BIGINT, ForeignKey("usuario.id", name="fk_modelo_documento__ativado_por")
    )
    ativo_marcador: Mapped[int | None] = mapped_column(
        mysql.TINYINT(unsigned=True), Computed("IF(ativo, 1, NULL)", persisted=True)
    )


class EmissaoDocumento(Base):
    """Cada emissão, sem o arquivo nem texto livre (DD-43): modelo, versão, referência e competência."""

    __tablename__ = "emissao_documento"
    __table_args__ = (Index("ix_emissao_documento__aviso", "paciente_id", "modelo", "competencia"),)

    id: Mapped[int] = mapped_column(BIGINT, primary_key=True, autoincrement=True)
    paciente_id: Mapped[int] = mapped_column(
        BIGINT, ForeignKey("paciente.id", name="fk_emissao_documento__paciente_id")
    )
    modelo: Mapped[str] = mapped_column(String(20))
    versao_modelo: Mapped[int] = mapped_column(mysql.INTEGER(unsigned=True))
    referencia: Mapped[str | None] = mapped_column(String(40))
    competencia: Mapped[str] = mapped_column(mysql.CHAR(7, charset="ascii", collation="ascii_bin"))
    emitido_em: Mapped[datetime] = mapped_column(INSTANTE)
    emitido_por: Mapped[int] = mapped_column(BIGINT, ForeignKey("usuario.id", name="fk_emissao_documento__emitido_por"))
