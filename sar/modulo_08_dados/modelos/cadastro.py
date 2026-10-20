"""Modelos do MOD-02 Cadastro (DDS §6.4). Espelham a 0001; um teste de integração confere contra o banco
migrado. Sem relacionamentos: o repositório carrega o agregado explicitamente (DD-12)."""

from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import CheckConstraint, Computed, Date, Enum, ForeignKey, Index, String, UniqueConstraint
from sqlalchemy.dialects import mysql
from sqlalchemy.orm import Mapped, mapped_column

from sar.modulo_08_dados.modelos import Base

BIGINT = mysql.BIGINT(unsigned=True)
INSTANTE = mysql.DATETIME(fsp=6)
TIPOS_EVENTO = ("obito", "alta", "transferencia", "transplante", "desistencia")


def _ascii(tamanho: int) -> mysql.CHAR:
    return mysql.CHAR(tamanho, charset="ascii", collation="ascii_bin")


def _paciente(tabela: str, coluna: str = "paciente_id") -> ForeignKey:
    return ForeignKey("paciente.id", name=f"fk_{tabela}__{coluna}")


def _municipio(coluna: str) -> ForeignKey:
    return ForeignKey("municipio.codigo_ibge", name=f"fk_paciente__{coluna}")


class Paciente(Base):
    __tablename__ = "paciente"
    __table_args__ = (
        UniqueConstraint("prontuario", name="uq_paciente__prontuario"),  # P-03, INV-07
        UniqueConstraint("cpf", name="uq_paciente__cpf"),  # INV-15
        UniqueConstraint("cns", name="uq_paciente__cns"),  # INV-15
        CheckConstraint("cpf REGEXP '^[0-9]{11}$'", name="cpf"),
        CheckConstraint("cns REGEXP '^[0-9]{15}$'", name="cns"),
        CheckConstraint("cep REGEXP '^[0-9]{8}$'", name="cep"),
        # DD-89: só o anulado fica sem prontuário e nome; o mínimo da P-03 vale para os demais (0005)
        CheckConstraint("(prontuario IS NOT NULL AND nome IS NOT NULL) OR anulado_em IS NOT NULL", name="minimo"),
        Index("ix_paciente__nome", "nome"),
        Index("ix_paciente__nascimento", "data_nascimento"),
    )

    id: Mapped[int] = mapped_column(BIGINT, primary_key=True, autoincrement=True)
    prontuario: Mapped[str | None] = mapped_column(String(20))
    nome: Mapped[str | None] = mapped_column(String(150))
    data_nascimento: Mapped[date | None] = mapped_column(Date)
    sexo: Mapped[str | None] = mapped_column(Enum("F", "M", name="sexo"))
    nome_mae: Mapped[str | None] = mapped_column(String(150))
    cpf: Mapped[str | None] = mapped_column(_ascii(11))
    cns: Mapped[str | None] = mapped_column(_ascii(15))
    rg: Mapped[str | None] = mapped_column(String(20))
    rg_orgao: Mapped[str | None] = mapped_column(String(20))
    naturalidade_municipio_id: Mapped[str | None] = mapped_column(_ascii(7), _municipio("naturalidade_municipio_id"))
    logradouro: Mapped[str | None] = mapped_column(String(150))
    numero: Mapped[str | None] = mapped_column(String(10))
    complemento: Mapped[str | None] = mapped_column(String(60))
    bairro: Mapped[str | None] = mapped_column(String(80))
    municipio_id: Mapped[str | None] = mapped_column(_ascii(7), _municipio("municipio_id"))
    cep: Mapped[str | None] = mapped_column(_ascii(8))
    cep_verificado: Mapped[bool] = mapped_column(server_default="0")
    anulado_em: Mapped[datetime | None] = mapped_column(INSTANTE)
    criado_em: Mapped[datetime] = mapped_column(INSTANTE)
    versao: Mapped[int] = mapped_column(mysql.INTEGER(unsigned=True), server_default="1")


class Contato(Base):
    __tablename__ = "contato"

    id: Mapped[int] = mapped_column(BIGINT, primary_key=True, autoincrement=True)
    paciente_id: Mapped[int] = mapped_column(BIGINT, _paciente("contato"))
    nome: Mapped[str] = mapped_column(String(150))
    parentesco: Mapped[str | None] = mapped_column(String(40))


class Telefone(Base):
    __tablename__ = "telefone"
    __table_args__ = (CheckConstraint("(paciente_id IS NULL) <> (contato_id IS NULL)", name="um_dono"),)  # INV-12

    id: Mapped[int] = mapped_column(BIGINT, primary_key=True, autoincrement=True)
    paciente_id: Mapped[int | None] = mapped_column(BIGINT, _paciente("telefone"))
    contato_id: Mapped[int | None] = mapped_column(BIGINT, ForeignKey("contato.id", name="fk_telefone__contato_id"))
    ddd: Mapped[str] = mapped_column(_ascii(2))
    numero: Mapped[str] = mapped_column(String(9))
    tipo: Mapped[str] = mapped_column(Enum("celular", "fixo", "recado", name="tipo_telefone"))


class PeriodoTratamento(Base):
    """Evento embutido (DD-13), com o comprovante ligado ao documento do MOD-04 (§6.5)."""

    __tablename__ = "periodo_tratamento"
    __table_args__ = (
        UniqueConstraint("paciente_id", "aberto", name="uq_periodo_tratamento__um_aberto"),  # INV-02
        UniqueConstraint("paciente_id", "inicio", name="uq_periodo_tratamento__inicio"),
        CheckConstraint("(evento_tipo IS NULL) = (evento_data IS NULL)", name="evento"),
        CheckConstraint("evento_data IS NULL OR evento_data >= inicio", name="datas"),
        CheckConstraint("evento_documento_id IS NULL OR evento_tipo IS NOT NULL", name="comprovante"),
    )

    id: Mapped[int] = mapped_column(BIGINT, primary_key=True, autoincrement=True)
    paciente_id: Mapped[int] = mapped_column(BIGINT, _paciente("periodo_tratamento"))
    inicio: Mapped[date] = mapped_column(Date)
    medico_referencia: Mapped[str | None] = mapped_column(String(150))
    evento_tipo: Mapped[str | None] = mapped_column(Enum(*TIPOS_EVENTO, name="tipo_evento"))
    evento_data: Mapped[date | None] = mapped_column(Date)
    evento_local: Mapped[str | None] = mapped_column(String(150))
    evento_documento_id: Mapped[bytes | None] = mapped_column(
        mysql.BINARY(16), ForeignKey("documento.id", name="fk_periodo_tratamento__evento_documento_id")
    )
    evento_registrado_em: Mapped[datetime | None] = mapped_column(INSTANTE)
    aberto: Mapped[int | None] = mapped_column(
        mysql.TINYINT(unsigned=True), Computed("IF(evento_tipo IS NULL, 1, NULL)", persisted=True)
    )


class Cobertura(Base):
    """Só com início: o fim é o início da seguinte (DD-70)."""

    __tablename__ = "cobertura"
    __table_args__ = (
        UniqueConstraint("periodo_id", "vigencia_inicio", name="uq_cobertura__inicio"),
        CheckConstraint("(tipo = 'convenio') = (convenio_id IS NOT NULL)", name="convenio"),
    )

    id: Mapped[int] = mapped_column(BIGINT, primary_key=True, autoincrement=True)
    periodo_id: Mapped[int] = mapped_column(
        BIGINT, ForeignKey("periodo_tratamento.id", name="fk_cobertura__periodo_id")
    )
    vigencia_inicio: Mapped[date] = mapped_column(Date)
    tipo: Mapped[str] = mapped_column(Enum("sus", "convenio", name="tipo_cobertura"))
    convenio_id: Mapped[int | None] = mapped_column(BIGINT, ForeignKey("convenio.id", name="fk_cobertura__convenio_id"))
    carteirinha: Mapped[str | None] = mapped_column(String(30))


class DuplicidadeDescartada(Base):
    __tablename__ = "duplicidade_descartada"
    __table_args__ = (
        UniqueConstraint("paciente_a_id", "paciente_b_id", name="uq_duplicidade_descartada__par"),
        CheckConstraint("paciente_a_id < paciente_b_id", name="ordem"),
    )

    id: Mapped[int] = mapped_column(BIGINT, primary_key=True, autoincrement=True)
    paciente_a_id: Mapped[int] = mapped_column(BIGINT, _paciente("duplicidade_descartada", "paciente_a_id"))
    paciente_b_id: Mapped[int] = mapped_column(BIGINT, _paciente("duplicidade_descartada", "paciente_b_id"))
    decidido_por: Mapped[int] = mapped_column(
        BIGINT, ForeignKey("usuario.id", name="fk_duplicidade_descartada__decidido_por")
    )
    decidido_em: Mapped[datetime] = mapped_column(INSTANTE)


class RascunhoCadastro(Base):
    __tablename__ = "rascunho_cadastro"
    __table_args__ = (UniqueConstraint("usuario_id", name="uq_rascunho_cadastro__usuario"),)

    id: Mapped[int] = mapped_column(BIGINT, primary_key=True, autoincrement=True)
    usuario_id: Mapped[int] = mapped_column(BIGINT, ForeignKey("usuario.id", name="fk_rascunho_cadastro__usuario_id"))
    conteudo_cifrado: Mapped[bytes] = mapped_column(mysql.MEDIUMBLOB)
    nonce: Mapped[bytes] = mapped_column(mysql.BINARY(12))
    criado_em: Mapped[datetime] = mapped_column(INSTANTE)
    atualizado_em: Mapped[datetime] = mapped_column(INSTANTE)
