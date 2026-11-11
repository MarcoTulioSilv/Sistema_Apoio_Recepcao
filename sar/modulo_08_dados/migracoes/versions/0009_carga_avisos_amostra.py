"""Carga inicial (DDS §14.4, DD-114): avisos e amostra na linha, e o número de ativos confirmado no lote.

- `carga_linha.avisos`: códigos dos valores que não entraram e das conferências com a P4 (DD-22, RF-1106), sem o
  valor. A exceção de linha continua em `excecao_codigo`.
- `carga_linha.amostra_rodada`: rodada do sorteio da conferência amostral (P-29); nula se a linha não foi sorteada.
- `carga_lote.ativos_confirmados`: o número de pacientes em tratamento que a recepção confirmou contra a escala no
  dia (R-16), informado no aceite.

Nenhum privilégio muda: o sar_web já tem INSERT e UPDATE nas duas tabelas.

Revision ID: 0009
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("carga_linha", sa.Column("avisos", sa.JSON, nullable=True))
    op.add_column("carga_linha", sa.Column("amostra_rodada", mysql.TINYINT(unsigned=True), nullable=True))
    op.add_column("carga_lote", sa.Column("ativos_confirmados", mysql.INTEGER(unsigned=True), nullable=True))


def downgrade() -> None:
    op.drop_column("carga_lote", "ativos_confirmados")
    op.drop_column("carga_linha", "amostra_rodada")
    op.drop_column("carga_linha", "avisos")
