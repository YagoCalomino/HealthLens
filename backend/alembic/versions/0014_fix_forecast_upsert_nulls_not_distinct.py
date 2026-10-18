"""fix forecast_resultados upsert — replace UNIQUE CONSTRAINT with NULLS NOT DISTINCT unique index

Revision ID: 0014
Revises: 0013
Create Date: 2026-06-15
"""

from typing import Sequence, Union

from alembic import op

revision: str = "0014"
down_revision: Union[str, None] = "0013"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE forecast_resultados DROP CONSTRAINT IF EXISTS uq_forecast_resultados"
    )
    op.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS uq_forecast_resultados
            ON forecast_resultados (dim_local_id, dim_causa_id, metrica, ano_referencia, ano_forecast, modelo_utilizado)
            NULLS NOT DISTINCT
    """)


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS uq_forecast_resultados")
    # WARNING: the restored UNIQUE CONSTRAINT treats NULL dim_causa_id as DISTINCT.
    # ON CONFLICT will NOT deduplicate all-cause rows (dim_causa_id IS NULL),
    # causing duplicates on every run_forecasting() call.
    # Re-apply migration 0014 to restore correct behaviour.
    op.execute("""
        ALTER TABLE forecast_resultados
            ADD CONSTRAINT uq_forecast_resultados
                UNIQUE (dim_local_id, dim_causa_id, metrica, ano_referencia, ano_forecast, modelo_utilizado)
    """)
