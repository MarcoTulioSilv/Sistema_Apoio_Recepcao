"""Cursor das rotinas pesadas em `job_execucao` (DD-64, DDS §13.3).

A revarredura e a conferência de hash param às 04:30 e a execução seguinte continua de onde a anterior parou; o
cursor (id do último documento visto, em hexadecimal) fica na própria execução. Sem dado pessoal.

Revision ID: 0008
"""
import sqlalchemy as sa
from alembic import op

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("job_execucao", sa.Column("cursor", sa.String(64), nullable=True))


def downgrade() -> None:
    op.drop_column("job_execucao", "cursor")
