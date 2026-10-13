"""extend forecast_resultados — add CI columns, backtest metrics, update unique constraint

Revision ID: 0012
Revises: 0011
Create Date: 2026-06-12
"""

from typing import Sequence, Union

from alembic import op

revision: str = "0012"
down_revision: Union[str, None] = "0011"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Step 1 — Add new CI and backtest metric columns with IF NOT EXISTS for idempotency
    op.execute("""
        ALTER TABLE forecast_resultados
            ADD COLUMN IF NOT EXISTS intervalo_inferior_80 NUMERIC(12,4),
            ADD COLUMN IF NOT EXISTS intervalo_superior_80 NUMERIC(12,4),
            ADD COLUMN IF NOT EXISTS intervalo_inferior_95 NUMERIC(12,4),
            ADD COLUMN IF NOT EXISTS intervalo_superior_95 NUMERIC(12,4),
            ADD COLUMN IF NOT EXISTS mase                  NUMERIC(8,4),
            ADD COLUMN IF NOT EXISTS smape                 NUMERIC(8,4)
    """)

    # Step 2 — Drop old two-column CI schema (replaced by 80%/95% bands above)
    op.execute("""
        ALTER TABLE forecast_resultados
            DROP COLUMN IF EXISTS intervalo_inferior,
            DROP COLUMN IF EXISTS intervalo_superior
    """)

    # Step 3 — Drop existing constraint; PostgreSQL does not support ALTER CONSTRAINT
    op.execute("""
        ALTER TABLE forecast_resultados
            DROP CONSTRAINT IF EXISTS uq_forecast_resultados
    """)

    # Step 4 — Recreate constraint with modelo_utilizado included (one row per model per series)
    op.execute("""
        ALTER TABLE forecast_resultados
            ADD CONSTRAINT uq_forecast_resultados
                UNIQUE (dim_local_id, dim_causa_id, metrica, ano_referencia, ano_forecast, modelo_utilizado)
    """)


def downgrade() -> None:
    # Reverse Step 4 — drop new constraint
    op.execute("""
        ALTER TABLE forecast_resultados
            DROP CONSTRAINT IF EXISTS uq_forecast_resultados
    """)

    # Reverse Step 3 — restore old constraint without modelo_utilizado
    op.execute("""
        ALTER TABLE forecast_resultados
            ADD CONSTRAINT uq_forecast_resultados
                UNIQUE (dim_local_id, dim_causa_id, metrica, ano_referencia, ano_forecast)
    """)

    # Reverse Step 1 — drop new columns
    op.execute("""
        ALTER TABLE forecast_resultados
            DROP COLUMN IF EXISTS intervalo_inferior_80,
            DROP COLUMN IF EXISTS intervalo_superior_80,
            DROP COLUMN IF EXISTS intervalo_inferior_95,
            DROP COLUMN IF EXISTS intervalo_superior_95,
            DROP COLUMN IF EXISTS mase,
            DROP COLUMN IF EXISTS smape
    """)

    # Reverse Step 2 — restore old CI columns
    op.execute("""
        ALTER TABLE forecast_resultados
            ADD COLUMN IF NOT EXISTS intervalo_inferior NUMERIC(12,4),
            ADD COLUMN IF NOT EXISTS intervalo_superior NUMERIC(12,4)
    """)
