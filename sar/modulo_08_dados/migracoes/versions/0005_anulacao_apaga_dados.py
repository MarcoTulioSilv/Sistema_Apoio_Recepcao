"""Anulação apaga os dados pessoais do cadastro (DD-89, RF-1008).

`prontuario` e `nome` passam a aceitar nulo, só no paciente anulado: a verificação `ck_paciente__minimo` mantém
o mínimo da P-03 para todo cadastro ativo. A unicidade do prontuário continua; o índice único admite vários
nulos, e o número do cadastro anulado fica livre. O downgrade devolve um texto aos anulados antes de voltar a
exigir as colunas.

Revision ID: 0005
"""
import sqlalchemy as sa
from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column("paciente", "prontuario", existing_type=sa.String(20), nullable=True)
    op.alter_column("paciente", "nome", existing_type=sa.String(150), nullable=True)
    op.create_check_constraint(
        "ck_paciente__minimo", "paciente",
        "(prontuario IS NOT NULL AND nome IS NOT NULL) OR anulado_em IS NOT NULL",
    )


def downgrade() -> None:
    op.drop_constraint("ck_paciente__minimo", "paciente", type_="check")
    op.execute("UPDATE paciente SET prontuario = CONCAT('ANULADO-', id) WHERE prontuario IS NULL")
    op.execute("UPDATE paciente SET nome = 'Cadastro anulado' WHERE nome IS NULL")
    op.alter_column("paciente", "nome", existing_type=sa.String(150), nullable=False)
    op.alter_column("paciente", "prontuario", existing_type=sa.String(20), nullable=False)
