"""Âncora sem anotação manual (DD-86, DEC-74).

A âncora passou a sair no rodapé dos relatórios e documentos emitidos; a anotação mensal pela administração
deixou de existir, e o usuário sar_web já não tem privilégio nessas colunas. Remove `anotada_em` e
`anotada_por` (com a chave estrangeira para usuario). O downgrade as recria vazias, como na 0001.

Revision ID: 0004
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_constraint("fk_auditoria_ancora__anotada_por", "auditoria_ancora", type_="foreignkey")
    op.drop_index("fk_auditoria_ancora__anotada_por", table_name="auditoria_ancora")
    op.drop_column("auditoria_ancora", "anotada_por")
    op.drop_column("auditoria_ancora", "anotada_em")


def downgrade() -> None:
    op.add_column("auditoria_ancora", sa.Column("anotada_em", mysql.DATETIME(fsp=6), nullable=True))
    op.add_column("auditoria_ancora", sa.Column("anotada_por", mysql.BIGINT(unsigned=True), nullable=True))
    op.create_foreign_key("fk_auditoria_ancora__anotada_por", "auditoria_ancora", "usuario",
                          ["anotada_por"], ["id"])
