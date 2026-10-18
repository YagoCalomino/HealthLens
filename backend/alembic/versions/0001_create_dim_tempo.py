"""create dim_tempo

Revision ID: 0001
Revises:
Create Date: 2026-06-11
"""

from typing import Sequence, Union

from alembic import op

revision: str = "0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE dim_tempo (
            id          INTEGER PRIMARY KEY GENERATED ALWAYS AS IDENTITY,
            ano         SMALLINT NOT NULL,
            mes         SMALLINT,
            trimestre   SMALLINT,
            semestre    SMALLINT,
            CONSTRAINT uq_dim_tempo_ano_mes UNIQUE (ano, mes)
        )
    """)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS dim_tempo")
