"""Uma cobertura por período (DD-101, INV-09 emendada pela DEC-75).

A cobertura passa a valer do início ao fim do período: a unicidade de período e início dá lugar à unicidade do
período, e `vigencia_inicio` sai, porque seria sempre o início do período. Trocar de cobertura é encerrar o período
pelo evento e abrir outro. Com algum período ainda com mais de uma cobertura, a migração para sem mudar nada: quem
decide qual fica é a administração, não a migração. O downgrade devolve a coluna com o início do período.

Revision ID: 0006
"""
import sqlalchemy as sa
from alembic import op

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    repetidos = op.get_bind().execute(
        sa.text("SELECT periodo_id FROM cobertura GROUP BY periodo_id HAVING COUNT(*) > 1")
    ).scalars().all()
    if repetidos:
        raise RuntimeError(
            f"Períodos com mais de uma cobertura (ids {sorted(repetidos)}): deixe uma só em cada antes de migrar."
        )
    # A nova unicidade entra antes de a antiga sair: ela passa a ser o índice da chave estrangeira do período.
    op.create_unique_constraint("uq_cobertura__periodo", "cobertura", ["periodo_id"])
    op.drop_constraint("uq_cobertura__inicio", "cobertura", type_="unique")
    op.drop_column("cobertura", "vigencia_inicio")


def downgrade() -> None:
    op.add_column("cobertura", sa.Column("vigencia_inicio", sa.Date, nullable=True))
    op.execute(
        "UPDATE cobertura c JOIN periodo_tratamento p ON p.id = c.periodo_id SET c.vigencia_inicio = p.inicio"
    )
    op.alter_column("cobertura", "vigencia_inicio", existing_type=sa.Date, nullable=False)
    op.create_unique_constraint("uq_cobertura__inicio", "cobertura", ["periodo_id", "vigencia_inicio"])
    op.drop_constraint("uq_cobertura__periodo", "cobertura", type_="unique")
