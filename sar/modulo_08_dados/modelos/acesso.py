"""Modelos do MOD-01 Acesso e auditoria (DDS §5). Espelham a 0001 e a 0003; um teste de integração confere
contra o banco migrado. Sem relacionamentos: os repositórios carregam explicitamente o que precisam
(DD-12)."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import CheckConstraint, Computed, Enum, ForeignKey, Index, String, Text, UniqueConstraint
from sqlalchemy.dialects import mysql
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import JSON

from sar.modulo_08_dados.modelos import Base

BIGINT = mysql.BIGINT(unsigned=True)
INSTANTE = mysql.DATETIME(fsp=6)


def _ascii(tamanho: int) -> mysql.CHAR:
    return mysql.CHAR(tamanho, charset="ascii", collation="ascii_bin")


PERFIS = ("recepcao", "administracao", "visualizador", "ti", "enfermagem")
MOTIVOS_ENCERRAMENTO = ("saida", "inatividade", "limite", "novo_login", "inativacao")
ESTADOS_SOLICITACAO = ("pendente", "executada", "invalidada", "recusada", "cancelada")


class Usuario(Base):
    __tablename__ = "usuario"
    __table_args__ = (UniqueConstraint("login", name="uq_usuario__login"),)

    id: Mapped[int] = mapped_column(BIGINT, primary_key=True, autoincrement=True)
    nome: Mapped[str] = mapped_column(String(120))
    login: Mapped[str] = mapped_column(String(60))
    senha_hash: Mapped[str] = mapped_column(_ascii(60))
    perfil: Mapped[str] = mapped_column(Enum(*PERFIS, name="perfil"))
    ativo: Mapped[bool] = mapped_column(server_default="1")
    deve_trocar_senha: Mapped[bool] = mapped_column(server_default="1")
    termo_ciencia_em: Mapped[datetime | None] = mapped_column(INSTANTE)
    tentativas_falhas: Mapped[int] = mapped_column(mysql.SMALLINT(unsigned=True), server_default="0")
    bloqueado_ate: Mapped[datetime | None] = mapped_column(INSTANTE)
    criado_em: Mapped[datetime] = mapped_column(INSTANTE)
    versao: Mapped[int] = mapped_column(mysql.INTEGER(unsigned=True), server_default="1")

    # Concorrência otimista (DD-17). Forma exigida pelo SQLAlchemy, que o declara como atributo de instância.
    __mapper_args__ = {"version_id_col": versao}  # noqa: RUF012


class SessaoUsuario(Base):
    __tablename__ = "sessao_usuario"
    __table_args__ = (
        UniqueConstraint("token_hash", name="uq_sessao_usuario__token_hash"),
        UniqueConstraint("usuario_id", "ativa", name="uq_sessao_usuario__uma_ativa"),  # P-02
    )

    id: Mapped[int] = mapped_column(BIGINT, primary_key=True, autoincrement=True)
    token_hash: Mapped[str] = mapped_column(_ascii(64))  # SHA-256 do token; o token nunca é gravado (DD-05)
    usuario_id: Mapped[int] = mapped_column(BIGINT, ForeignKey("usuario.id", name="fk_sessao_usuario__usuario_id"))
    origem: Mapped[str] = mapped_column(String(45))
    criada_em: Mapped[datetime] = mapped_column(INSTANTE)
    ultimo_acesso: Mapped[datetime] = mapped_column(INSTANTE)
    encerrada_em: Mapped[datetime | None] = mapped_column(INSTANTE)
    motivo_encerramento: Mapped[str | None] = mapped_column(Enum(*MOTIVOS_ENCERRAMENTO, name="motivo_encerramento"))
    ativa: Mapped[int | None] = mapped_column(
        mysql.TINYINT(unsigned=True), Computed("IF(encerrada_em IS NULL, 1, NULL)", persisted=True)
    )


class Auditoria(Base):
    __tablename__ = "auditoria"
    __table_args__ = (
        UniqueConstraint("hash_registro", name="uq_auditoria__hash_registro"),
        Index("ix_auditoria__entidade", "entidade", "entidade_id"),
        Index("ix_auditoria__usuario_instante", "usuario_id", "instante"),
        Index("ix_auditoria__instante", "instante"),
        Index("ix_auditoria__requisicao", "requisicao_id"),
        Index("ix_auditoria__sessao", "sessao_id", "instante"),
    )

    id: Mapped[int] = mapped_column(BIGINT, primary_key=True, autoincrement=False)  # dado pela cabeça (DD-71)
    instante: Mapped[datetime] = mapped_column(INSTANTE)
    usuario_id: Mapped[int | None] = mapped_column(BIGINT, ForeignKey("usuario.id", name="fk_auditoria__usuario_id"))
    autorizador_id: Mapped[int | None] = mapped_column(
        BIGINT, ForeignKey("usuario.id", name="fk_auditoria__autorizador_id")
    )
    operacao: Mapped[str] = mapped_column(String(80))
    entidade: Mapped[str] = mapped_column(String(60))
    entidade_id: Mapped[str | None] = mapped_column(String(40))
    alteracoes: Mapped[str | None] = mapped_column(mysql.MEDIUMTEXT)  # texto canônico, nunca JSON (§3.10)
    motivo: Mapped[str | None] = mapped_column(String(500))
    origem: Mapped[str | None] = mapped_column(String(45))
    versao_formato: Mapped[int] = mapped_column(mysql.SMALLINT(unsigned=True))
    hash_anterior: Mapped[str] = mapped_column(_ascii(64))
    hash_registro: Mapped[str] = mapped_column(_ascii(64))
    sessao_id: Mapped[int | None] = mapped_column(
        BIGINT, ForeignKey("sessao_usuario.id", name="fk_auditoria__sessao_id")
    )
    requisicao_id: Mapped[str | None] = mapped_column(_ascii(32))


class AuditoriaCabeca(Base):
    __tablename__ = "auditoria_cabeca"
    __table_args__ = (CheckConstraint("id = 1", name="ck_auditoria_cabeca__linha_unica"),)

    id: Mapped[int] = mapped_column(mysql.TINYINT(unsigned=True), primary_key=True, autoincrement=False)
    ultimo_registro_id: Mapped[int] = mapped_column(BIGINT)
    ultimo_hash: Mapped[str] = mapped_column(_ascii(64))


class AuditoriaAncora(Base):
    __tablename__ = "auditoria_ancora"

    id: Mapped[int] = mapped_column(BIGINT, primary_key=True, autoincrement=True)
    ate_registro_id: Mapped[int] = mapped_column(BIGINT)
    hash: Mapped[str] = mapped_column(_ascii(64))
    registrada_em: Mapped[datetime] = mapped_column(INSTANTE)
    anotada_em: Mapped[datetime | None] = mapped_column(INSTANTE)
    anotada_por: Mapped[int | None] = mapped_column(
        BIGINT, ForeignKey("usuario.id", name="fk_auditoria_ancora__anotada_por")
    )


class AuditoriaCorte(Base):
    __tablename__ = "auditoria_corte"

    id: Mapped[int] = mapped_column(BIGINT, primary_key=True, autoincrement=True)
    primeiro_id_remanescente: Mapped[int] = mapped_column(BIGINT)
    hash_anterior: Mapped[str] = mapped_column(_ascii(64))
    executado_em: Mapped[datetime] = mapped_column(INSTANTE)
    registros_expurgados: Mapped[int] = mapped_column(BIGINT)


class AvisoIntegridade(Base):
    __tablename__ = "aviso_integridade"
    __table_args__ = (
        CheckConstraint("(encerrado_em IS NULL) = (explicacao IS NULL)", name="ck_aviso_integridade__encerramento"),
    )

    id: Mapped[int] = mapped_column(BIGINT, primary_key=True, autoincrement=True)
    detectado_em: Mapped[datetime] = mapped_column(INSTANTE)
    registro_divergente_id: Mapped[int] = mapped_column(BIGINT)
    encerrado_em: Mapped[datetime | None] = mapped_column(INSTANTE)
    encerrado_por: Mapped[int | None] = mapped_column(
        BIGINT, ForeignKey("usuario.id", name="fk_aviso_integridade__encerrado_por")
    )
    explicacao: Mapped[str | None] = mapped_column(Text)


class SolicitacaoAutorizacao(Base):
    __tablename__ = "solicitacao_autorizacao"
    __table_args__ = (Index("ix_solicitacao_autorizacao__estado", "estado", "solicitada_em"),)

    id: Mapped[bytes] = mapped_column(mysql.BINARY(16), primary_key=True)  # aleatório: aparece em URL (§3.6)
    tipo: Mapped[str] = mapped_column(String(80))
    entidade: Mapped[str] = mapped_column(String(60))
    entidade_id: Mapped[str] = mapped_column(String(40))
    parametros: Mapped[dict[str, Any]] = mapped_column(JSON)
    versao_alvo: Mapped[int | None] = mapped_column(mysql.INTEGER(unsigned=True))
    motivo: Mapped[str] = mapped_column(String(500))
    solicitante_id: Mapped[int] = mapped_column(
        BIGINT, ForeignKey("usuario.id", name="fk_solicitacao_autorizacao__solicitante_id")
    )
    solicitada_em: Mapped[datetime] = mapped_column(INSTANTE)
    estado: Mapped[str] = mapped_column(Enum(*ESTADOS_SOLICITACAO, name="estado_solicitacao"))
    decisor_id: Mapped[int | None] = mapped_column(
        BIGINT, ForeignKey("usuario.id", name="fk_solicitacao_autorizacao__decisor_id")
    )
    decidida_em: Mapped[datetime | None] = mapped_column(INSTANTE)
    motivo_decisao: Mapped[str | None] = mapped_column(String(500))
