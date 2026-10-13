"""add dt_notific to fato_notificacoes

Revision ID: 0020
Revises: 0019
Create Date: 2026-08-10

Persists the real SINAN notification date so an epidemic curve by semana
epidemiologica becomes computable. `dim_tempo` is (ano, mes) only —
monthly grain — and PostgreSQL has no built-in DataSUS-convention epi-week
function, so the raw date is stored here and the Sunday-anchored epi-week
number is derived in Python at API response time, never as a generated
column.

Column is nullable on purpose: the 9,998 pre-existing ANIM/2023 rows loaded
during the first SINAN rehearsal have no value until the standalone backfill
script (scripts/backfill_dt_notific.py) runs against cached SINAN Parquet. A
fresh SINAN load populates it directly via the staging and loader code
(etl/staging/sinan_staging.py, etl/mart/notificacoes_loader.py).
"""

from typing import Sequence, Union

from alembic import op

revision: str = "0020"
down_revision: Union[str, None] = "0019"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("""
        ALTER TABLE fato_notificacoes ADD COLUMN dt_notific DATE
    """)
    op.execute("""
        CREATE INDEX ix_fato_notificacoes_dt_notific
        ON fato_notificacoes (dim_agravo_id, dt_notific)
    """)


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_fato_notificacoes_dt_notific")
    op.execute("""
        ALTER TABLE fato_notificacoes DROP COLUMN IF EXISTS dt_notific
    """)
