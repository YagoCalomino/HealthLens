"""create dim_faixa_etaria

Revision ID: 0004
Revises: 0003
Create Date: 2026-06-11
"""

from typing import Sequence, Union

from alembic import op

revision: str = "0004"
down_revision: Union[str, None] = "0003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE dim_faixa_etaria (
            id         INTEGER PRIMARY KEY GENERATED ALWAYS AS IDENTITY,
            codigo     VARCHAR(10) NOT NULL,
            descricao  VARCHAR(50) NOT NULL,
            idade_min  SMALLINT NOT NULL,
            idade_max  SMALLINT,
            ordem      SMALLINT NOT NULL,
            CONSTRAINT uq_dim_faixa_etaria_codigo UNIQUE (codigo)
        )
    """)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS dim_faixa_etaria")
