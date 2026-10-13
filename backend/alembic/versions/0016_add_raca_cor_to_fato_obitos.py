"""add raca_cor to fato_obitos

Revision ID: 0016
Revises: 0015
Create Date: 2026-07-26
"""

from typing import Sequence, Union

from alembic import op

revision: str = "0016"
down_revision: Union[str, None] = "0015"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("""
        ALTER TABLE fato_obitos
            ADD COLUMN IF NOT EXISTS raca_cor CHAR(1)
    """)


def downgrade() -> None:
    op.execute("""
        ALTER TABLE fato_obitos
            DROP COLUMN IF EXISTS raca_cor
    """)
