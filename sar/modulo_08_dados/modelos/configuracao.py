"""Modelos do MOD-06 Configuração (DDS §10.4)."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import CheckConstraint, ForeignKey, Index, String, UniqueConstraint
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


class Convenio(Base):
    """Inativado, nunca excluído (DD-49): a cobertura antiga continua apontando para ele."""

    __tablename__ = "convenio"
    __table_args__ = (UniqueConstraint("nome", name="uq_convenio__nome"),)

    id: Mapped[int] = mapped_column(mysql.BIGINT(unsigned=True), primary_key=True, autoincrement=True)
    nome: Mapped[str] = mapped_column(String(100))
    ativo: Mapped[bool] = mapped_column(server_default="1")


class Municipio(Base):
    """Tabela do IBGE com 7 dígitos, carregada na migração (DD-52, DD-53)."""

    __tablename__ = "municipio"
    __table_args__ = (
        CheckConstraint("codigo_ibge REGEXP '^[0-9]{7}$'", name="codigo"),
        Index("ix_municipio__uf_nome", "uf", "nome"),
    )

    codigo_ibge: Mapped[str] = mapped_column(mysql.CHAR(7, charset="ascii", collation="ascii_bin"), primary_key=True)
    nome: Mapped[str] = mapped_column(String(80))
    uf: Mapped[str] = mapped_column(mysql.CHAR(2, charset="ascii", collation="ascii_bin"))
    incluido_em: Mapped[datetime | None] = mapped_column(mysql.DATETIME(fsp=6))
    incluido_por: Mapped[int | None] = mapped_column(
        mysql.BIGINT(unsigned=True), ForeignKey("usuario.id", name="fk_municipio__incluido_por")
    )


class Instituicao(Base):
    """Linha única (id = 1): o cabeçalho dos documentos e o logotipo (RF-1201, RF-1202)."""

    __tablename__ = "instituicao"
    __table_args__ = (CheckConstraint("id = 1", name="linha_unica"),)

    id: Mapped[int] = mapped_column(mysql.TINYINT(unsigned=True), primary_key=True, autoincrement=False)
    nome: Mapped[str] = mapped_column(String(150))
    endereco: Mapped[str] = mapped_column(String(200))
    cep: Mapped[str] = mapped_column(mysql.CHAR(8, charset="ascii", collation="ascii_bin"))
    municipio_id: Mapped[str] = mapped_column(
        mysql.CHAR(7, charset="ascii", collation="ascii_bin"),
        ForeignKey("municipio.codigo_ibge", name="fk_instituicao__municipio_id"),
    )
    uf: Mapped[str] = mapped_column(mysql.CHAR(2, charset="ascii", collation="ascii_bin"))
    telefone: Mapped[str | None] = mapped_column(String(20))
    cnpj: Mapped[str | None] = mapped_column(mysql.CHAR(14, charset="ascii", collation="ascii_bin"))
    logotipo: Mapped[bytes | None] = mapped_column(mysql.MEDIUMBLOB, deferred=True)
    logotipo_tipo: Mapped[str | None] = mapped_column(mysql.ENUM("png", "jpeg"))


class FaixaEtaria(Base):
    """Carregada pela migração 0002 (RF-1206, DEC-49); só leitura."""

    __tablename__ = "faixa_etaria"
    __table_args__ = (UniqueConstraint("inicio", name="uq_faixa_etaria__inicio"),)

    id: Mapped[int] = mapped_column(mysql.BIGINT(unsigned=True), primary_key=True)
    inicio: Mapped[int] = mapped_column(mysql.SMALLINT(unsigned=True))
    fim: Mapped[int | None] = mapped_column(mysql.SMALLINT(unsigned=True))
    rotulo: Mapped[str] = mapped_column(String(20))
