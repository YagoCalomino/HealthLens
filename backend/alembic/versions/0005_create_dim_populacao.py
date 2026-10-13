"""create dim_populacao

Revision ID: 0005
Revises: 0004
Create Date: 2026-06-11
"""

from typing import Sequence, Union

from alembic import op

revision: str = "0005"
down_revision: Union[str, None] = "0004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE dim_populacao (
            id                INTEGER PRIMARY KEY GENERATED ALWAYS AS IDENTITY,
            codigo_ibge_6     CHAR(6) NOT NULL,
            ano               SMALLINT NOT NULL,
            populacao_total   INTEGER NOT NULL,
            fonte             VARCHAR(50) NOT NULL DEFAULT 'TCU',
            CONSTRAINT uq_dim_populacao_ibge6_ano UNIQUE (codigo_ibge_6, ano)
        )
    """)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS dim_populacao")
