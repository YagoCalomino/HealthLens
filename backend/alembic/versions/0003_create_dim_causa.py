"""create dim_causa

Revision ID: 0003
Revises: 0002
Create Date: 2026-06-11
"""

from typing import Sequence, Union

from alembic import op

revision: str = "0003"
down_revision: Union[str, None] = "0002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE dim_causa (
            id             INTEGER PRIMARY KEY GENERATED ALWAYS AS IDENTITY,
            codigo_cid10   VARCHAR(5) NOT NULL,
            descricao      VARCHAR(500) NOT NULL,
            capitulo       VARCHAR(5) NOT NULL,
            categoria      VARCHAR(5) NOT NULL,
            subcategoria   VARCHAR(5),
            grupo_descricao VARCHAR(200),
            CONSTRAINT uq_dim_causa_cid10 UNIQUE (codigo_cid10)
        )
    """)
    op.execute("CREATE INDEX ix_dim_causa_capitulo ON dim_causa (capitulo)")
    op.execute("CREATE INDEX ix_dim_causa_categoria ON dim_causa (categoria)")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS dim_causa")
