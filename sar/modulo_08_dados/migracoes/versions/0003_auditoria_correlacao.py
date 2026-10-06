"""Correlação da trilha de auditoria com a sessão e a requisição (DD-81).

Acrescenta à auditoria a sessão do usuário e o id da requisição, para reconstruir a linha do tempo de
uma sessão e ligar um registro de auditoria às linhas do log técnico da mesma requisição. As duas
colunas entram na serialização canônica do hash (DDS §3.10).

Revision ID: 0003
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("auditoria", sa.Column("sessao_id", mysql.BIGINT(unsigned=True), nullable=True))
    op.add_column("auditoria", sa.Column("requisicao_id", mysql.CHAR(32, charset="ascii", collation="ascii_bin"),
                                         nullable=True))
    op.create_foreign_key("fk_auditoria__sessao_id", "auditoria", "sessao_usuario", ["sessao_id"], ["id"])
    op.create_index("ix_auditoria__requisicao", "auditoria", ["requisicao_id"])
    op.create_index("ix_auditoria__sessao", "auditoria", ["sessao_id", "instante"])


def downgrade() -> None:
    op.drop_constraint("fk_auditoria__sessao_id", "auditoria", type_="foreignkey")
    op.drop_index("ix_auditoria__sessao", table_name="auditoria")
    op.drop_index("ix_auditoria__requisicao", table_name="auditoria")
    op.drop_column("auditoria", "requisicao_id")
    op.drop_column("auditoria", "sessao_id")
