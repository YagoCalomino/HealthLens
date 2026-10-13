"""create fato_internacoes

Revision ID: 0007
Revises: 0006
Create Date: 2026-06-11
"""

# SIH AIH overcounting prevention: only SP_TIPO=1 rows loaded. Filter enforced in ETL, not DB constraint.
from typing import Sequence, Union

from alembic import op

revision: str = "0007"
down_revision: Union[str, None] = "0006"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE fato_internacoes (
            id                  BIGINT PRIMARY KEY GENERATED ALWAYS AS IDENTITY,
            dim_tempo_id        INTEGER NOT NULL REFERENCES dim_tempo(id),
            dim_local_id        INTEGER NOT NULL REFERENCES dim_local(id),
            dim_causa_id        INTEGER NOT NULL REFERENCES dim_causa(id),
            dim_faixa_etaria_id INTEGER NOT NULL REFERENCES dim_faixa_etaria(id),
            aih_numero          VARCHAR(20) NOT NULL,
            sp_tipo             SMALLINT NOT NULL DEFAULT 1,
            internacoes         INTEGER NOT NULL DEFAULT 1,
            obitos_internacao   INTEGER NOT NULL DEFAULT 0,
            dias_permanencia    INTEGER,
            taxa_por_100k       NUMERIC(10, 4),
            valor_total         NUMERIC(12, 2),
            CONSTRAINT uq_fato_internacoes_aih UNIQUE (aih_numero)
        )
    """)
    op.execute("""
        CREATE INDEX ix_fato_internacoes_tempo_local_causa
        ON fato_internacoes (dim_tempo_id, dim_local_id, dim_causa_id)
    """)
    op.execute(
        "CREATE INDEX ix_fato_internacoes_local ON fato_internacoes (dim_local_id)"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS fato_internacoes")
