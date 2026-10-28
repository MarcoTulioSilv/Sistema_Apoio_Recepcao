"""Parentesco do contato só da lista fechada (DD-102).

A ficha aceitava texto livre no parentesco, enquanto o novo cadastro já oferecia a lista. O que estiver gravado
fora da lista passa a "Outro parente"; o nome do contato não muda. Não há volta: o texto antigo não é guardado,
e o downgrade não mexe nos dados.

Revision ID: 0007
"""
import sqlalchemy as sa
from alembic import op

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None

# A lista da DD-102 na data desta migração (sar.modulo_02_cadastro.contrato.PARENTESCOS), copiada para a migração
# não mudar se a lista mudar depois.
PARENTESCOS = ("Cônjuge", "Filho ou filha", "Pai ou mãe", "Irmão ou irmã", "Outro parente", "Vizinho ou amigo")


def upgrade() -> None:
    op.execute("UPDATE contato SET parentesco = NULL WHERE TRIM(parentesco) = ''")  # vazio é sem parentesco
    op.get_bind().execute(
        sa.text(
            "UPDATE contato SET parentesco = 'Outro parente'"
            " WHERE parentesco IS NOT NULL AND parentesco NOT IN :lista"
        ).bindparams(sa.bindparam("lista", expanding=True)),
        {"lista": list(PARENTESCOS)},
    )


def downgrade() -> None:
    pass
