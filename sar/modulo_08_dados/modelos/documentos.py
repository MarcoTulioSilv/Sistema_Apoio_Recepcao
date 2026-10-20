"""Modelos do MOD-04 Documentos (DDS §8.7). Espelham a 0001; um teste de integração confere contra o banco migrado.
Sem relacionamentos: o repositório carrega o agregado explicitamente (DD-12)."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    Enum,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    LargeBinary,
    String,
    UniqueConstraint,
)
from sqlalchemy.dialects import mysql
from sqlalchemy.orm import Mapped, mapped_column

from sar.modulo_08_dados.modelos import Base

BIGINT = mysql.BIGINT(unsigned=True)
SMALLINT = mysql.SMALLINT(unsigned=True)
INSTANTE = mysql.DATETIME(fsp=6)
UUID = mysql.BINARY(16)
ORIGEM = Enum("scanner", "webcam", name="origem_captura")
TIPOS_EVENTO = ("obito", "alta", "transferencia", "transplante", "desistencia")
ESTADOS_INGESTAO = ("aberta", "recebida", "em_processamento", "aguardando_conferencia", "incorporada", "rejeitada",
                    "expirada", "cancelada")  # fmt: skip


def _ascii(tamanho: int) -> mysql.CHAR:
    return mysql.CHAR(tamanho, charset="ascii", collation="ascii_bin")


def _fk(tabela: str, coluna: str, alvo: str) -> ForeignKey:
    return ForeignKey(alvo, name=f"fk_{tabela}__{coluna}")


class TipoDocumento(Base):
    """Tabela fixa, carregada pela 0002 (DEC-41); nunca configurável pela tela."""

    __tablename__ = "tipo_documento"

    codigo: Mapped[str] = mapped_column(String(40), primary_key=True)
    nome: Mapped[str] = mapped_column(String(120))
    familia: Mapped[str] = mapped_column(Enum("cadastro", "prontuario", name="familia"))
    anos_retencao: Mapped[int] = mapped_column(SMALLINT)
    checklist: Mapped[str] = mapped_column(Enum("nao", "sempre", "se_convenio", name="checklist"))
    evento_exigente: Mapped[str | None] = mapped_column(Enum(*TIPOS_EVENTO, name="tipo_evento"))
    origem: Mapped[str] = mapped_column(ORIGEM)
    campos_extracao: Mapped[str | None] = mapped_column(String(200))


class Documento(Base):
    """Imutável (INV-06): arquivo, hash e chave nunca mudam; versão e vínculo são metadados (DD-36)."""

    __tablename__ = "documento"
    __table_args__ = (
        UniqueConstraint("arquivo", name="uq_documento__arquivo"),
        UniqueConstraint("hash_sha256", name="uq_documento__hash"),
        UniqueConstraint("substitui_id", name="uq_documento__substitui"),
        ForeignKeyConstraint(["substitui_id"], ["documento.id"], name="fk_documento__substitui_id"),
        CheckConstraint("(descartado_em IS NULL) = (chave_cifrada IS NOT NULL)", name="descarte"),
        CheckConstraint("(bloqueado_em IS NULL) = (bloqueio_motivo IS NULL)", name="bloqueio"),
        Index("ix_documento__paciente_tipo", "paciente_id", "tipo"),
    )

    id: Mapped[bytes] = mapped_column(UUID, primary_key=True)
    paciente_id: Mapped[int] = mapped_column(BIGINT, _fk("documento", "paciente_id", "paciente.id"))
    tipo: Mapped[str] = mapped_column(String(40), _fk("documento", "tipo", "tipo_documento.codigo"))
    versao: Mapped[int] = mapped_column(SMALLINT)
    substitui_id: Mapped[bytes | None] = mapped_column(UUID)
    arquivo: Mapped[str] = mapped_column(_ascii(36))
    chave_cifrada: Mapped[bytes | None] = mapped_column(mysql.VARBINARY(128))  # NULL após o descarte (DD-04)
    nonce: Mapped[bytes] = mapped_column(mysql.BINARY(12))
    hash_sha256: Mapped[str] = mapped_column(_ascii(64))
    prova_encadeamento: Mapped[str | None] = mapped_column(_ascii(64))  # preenchida no commit (DD-37)
    paginas: Mapped[int] = mapped_column(SMALLINT)
    origem: Mapped[str] = mapped_column(ORIGEM)
    capturado_em: Mapped[datetime] = mapped_column(INSTANTE)
    capturado_por: Mapped[int] = mapped_column(BIGINT, _fk("documento", "capturado_por", "usuario.id"))
    local_digitalizacao: Mapped[str] = mapped_column(String(80))  # DD-11
    descartado_em: Mapped[datetime | None] = mapped_column(INSTANTE)
    bloqueado_em: Mapped[datetime | None] = mapped_column(INSTANTE)
    bloqueio_motivo: Mapped[str | None] = mapped_column(Enum("rescan", "hash_divergente", name="motivo_bloqueio"))


class Ingestao(Base):
    """O estado é a fila (DD-33); uma ingestão gera no máximo um documento (§8.1)."""

    __tablename__ = "ingestao"
    __table_args__ = (
        ForeignKeyConstraint(["substitui_id"], ["documento.id"], name="fk_ingestao__substitui_id"),
        ForeignKeyConstraint(["documento_id"], ["documento.id"], name="fk_ingestao__documento_id"),
        UniqueConstraint("token_hash", name="uq_ingestao__token_hash"),
        UniqueConstraint("documento_id", name="uq_ingestao__documento"),
        CheckConstraint("estado = 'aguardando_conferencia' OR campos_candidatos_cifrados IS NULL", name="candidatos"),
        Index("ix_ingestao__fila", "estado", "criada_em"),
    )

    id: Mapped[bytes] = mapped_column(UUID, primary_key=True)
    paciente_id: Mapped[int] = mapped_column(BIGINT, _fk("ingestao", "paciente_id", "paciente.id"))
    tipo: Mapped[str] = mapped_column(String(40), _fk("ingestao", "tipo", "tipo_documento.codigo"))
    origem: Mapped[str] = mapped_column(ORIGEM)
    vinculo: Mapped[str | None] = mapped_column(String(80))
    substitui_id: Mapped[bytes | None] = mapped_column(UUID)
    estado: Mapped[str] = mapped_column(Enum(*ESTADOS_INGESTAO, name="estado_ingestao"))
    motivo_rejeicao: Mapped[str | None] = mapped_column(String(60))
    token_hash: Mapped[str | None] = mapped_column(_ascii(64))
    hash_entrada: Mapped[str | None] = mapped_column(_ascii(64))
    hash_reconstruido: Mapped[str | None] = mapped_column(_ascii(64))
    paginas: Mapped[int | None] = mapped_column(SMALLINT)
    campos_candidatos_cifrados: Mapped[bytes | None] = mapped_column(LargeBinary)  # P-18
    documento_id: Mapped[bytes | None] = mapped_column(UUID)
    criada_em: Mapped[datetime] = mapped_column(INSTANTE)
    criada_por: Mapped[int] = mapped_column(BIGINT, _fk("ingestao", "criada_por", "usuario.id"))
    atualizada_em: Mapped[datetime] = mapped_column(INSTANTE)
