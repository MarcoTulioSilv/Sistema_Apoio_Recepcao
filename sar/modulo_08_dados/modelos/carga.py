"""Modelos do MOD-10 Carga inicial (DDS §14.4). Espelham a 0001 e a 0009 (avisos, amostra e ativos confirmados)."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import Computed, Enum, ForeignKey, String, UniqueConstraint
from sqlalchemy.dialects import mysql
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import JSON

from sar.modulo_08_dados.modelos import Base

BIGINT = mysql.BIGINT(unsigned=True)
INSTANTE = mysql.DATETIME(fsp=6)


class CargaLote(Base):
    """Uma execução da carga: simulação, quantas vezes for preciso, ou a efetivação, uma só (DD-66, DD-72). As
    contagens são só números, por planilha e por código (DD-65)."""

    __tablename__ = "carga_lote"
    __table_args__ = (UniqueConstraint("efetivacao_valida", name="uq_carga_lote__uma_efetivacao"),)

    id: Mapped[int] = mapped_column(BIGINT, primary_key=True, autoincrement=True)
    modo: Mapped[str] = mapped_column(Enum("simulacao", "efetivacao", name="modo_carga"))
    situacao: Mapped[str] = mapped_column(Enum("em_andamento", "concluida", "falhou", "aceita", name="situacao_carga"))
    contagens: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    iniciado_em: Mapped[datetime] = mapped_column(INSTANTE)
    concluido_em: Mapped[datetime | None] = mapped_column(INSTANTE)
    aceito_em: Mapped[datetime | None] = mapped_column(INSTANTE)
    aceito_por: Mapped[int | None] = mapped_column(BIGINT, ForeignKey("usuario.id", name="fk_carga_lote__aceito_por"))
    efetivacao_valida: Mapped[int | None] = mapped_column(
        mysql.TINYINT(unsigned=True),
        Computed("IF(modo = 'efetivacao' AND situacao <> 'falhou', 1, NULL)", persisted=True),
    )
    ativos_confirmados: Mapped[int | None] = mapped_column(mysql.INTEGER(unsigned=True))


class CargaLinha(Base):
    """Um registro de origem, cifrado (DD-69): apagado no aceite."""

    __tablename__ = "carga_linha"
    __table_args__ = (UniqueConstraint("lote_id", "planilha", "numero_linha", name="uq_carga_linha__origem"),)

    id: Mapped[int] = mapped_column(BIGINT, primary_key=True, autoincrement=True)
    lote_id: Mapped[int] = mapped_column(BIGINT, ForeignKey("carga_lote.id", name="fk_carga_linha__lote_id"))
    planilha: Mapped[str] = mapped_column(String(40))
    numero_linha: Mapped[int] = mapped_column(mysql.INTEGER(unsigned=True))
    conteudo_cifrado: Mapped[bytes] = mapped_column(mysql.MEDIUMBLOB)
    nonce: Mapped[bytes] = mapped_column(mysql.BINARY(12))
    paciente_id: Mapped[int | None] = mapped_column(
        BIGINT, ForeignKey("paciente.id", name="fk_carga_linha__paciente_id")
    )
    excecao_codigo: Mapped[str | None] = mapped_column(String(40))
    excecao_tratada: Mapped[str | None] = mapped_column(
        Enum("importada_manual", "descartada", name="tratamento_excecao")
    )
    excecao_motivo: Mapped[str | None] = mapped_column(String(300))
    avisos: Mapped[list[str] | None] = mapped_column(JSON(none_as_null=True))  # sem aviso: NULL, não o JSON null
    amostra_rodada: Mapped[int | None] = mapped_column(mysql.TINYINT(unsigned=True))


class CargaConferencia(Base):
    """Um campo de um paciente sorteado, conferido contra a planilha (§14.3). Apagada no aceite."""

    __tablename__ = "carga_conferencia"
    __table_args__ = (UniqueConstraint("paciente_id", "campo", name="uq_carga_conferencia__campo"),)

    id: Mapped[int] = mapped_column(BIGINT, primary_key=True, autoincrement=True)
    paciente_id: Mapped[int] = mapped_column(
        BIGINT, ForeignKey("paciente.id", name="fk_carga_conferencia__paciente_id")
    )
    campo: Mapped[str] = mapped_column(String(40))
    resultado: Mapped[str] = mapped_column(Enum("conferido", "divergente", name="resultado_conferencia"))
    conferido_por: Mapped[int] = mapped_column(
        BIGINT, ForeignKey("usuario.id", name="fk_carga_conferencia__conferido_por")
    )
    conferido_em: Mapped[datetime] = mapped_column(INSTANTE)
