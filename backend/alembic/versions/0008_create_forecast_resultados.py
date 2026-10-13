"""create forecast_resultados

Revision ID: 0008
Revises: 0007
Create Date: 2026-06-11
"""

# ML pre-compute architecture: tables populated offline by ML runner. API is read-only.
from typing import Sequence, Union

from alembic import op

revision: str = "0008"
down_revision: Union[str, None] = "0007"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE forecast_resultados (
            id                  BIGINT PRIMARY KEY GENERATED ALWAYS AS IDENTITY,
            dim_local_id        INTEGER NOT NULL REFERENCES dim_local(id),
            dim_causa_id        INTEGER REFERENCES dim_causa(id),
            granularidade       VARCHAR(20) NOT NULL,
            metrica             VARCHAR(30) NOT NULL,
            ano_referencia      SMALLINT NOT NULL,
            ano_forecast        SMALLINT NOT NULL,
            valor_previsto      NUMERIC(12, 4) NOT NULL,
            intervalo_inferior  NUMERIC(12, 4),
            intervalo_superior  NUMERIC(12, 4),
            modelo_utilizado    VARCHAR(50) NOT NULL,
            criado_em           TIMESTAMP NOT NULL DEFAULT now(),
            CONSTRAINT uq_forecast_resultados
                UNIQUE (dim_local_id, dim_causa_id, metrica, ano_referencia, ano_forecast)
        )
    """)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS forecast_resultados")
