"""create fato_obitos

Revision ID: 0006
Revises: 0005
Create Date: 2026-06-11
"""

# SIM revision support: upsert key = (numero_do, revisao_numero).
from typing import Sequence, Union

from alembic import op

revision: str = "0006"
down_revision: Union[str, None] = "0005"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE fato_obitos (
            id                  BIGINT PRIMARY KEY GENERATED ALWAYS AS IDENTITY,
            dim_tempo_id        INTEGER NOT NULL REFERENCES dim_tempo(id),
            dim_local_id        INTEGER NOT NULL REFERENCES dim_local(id),
            dim_causa_id        INTEGER NOT NULL REFERENCES dim_causa(id),
            dim_faixa_etaria_id INTEGER NOT NULL REFERENCES dim_faixa_etaria(id),
            revisao_numero      SMALLINT NOT NULL DEFAULT 0,
            numero_do           VARCHAR(20) NOT NULL,
            obitos              INTEGER NOT NULL DEFAULT 1,
            taxa_por_100k       NUMERIC(10, 4),
            sexo                CHAR(1),
            idade_anos          SMALLINT,
            CONSTRAINT uq_fato_obitos_numerodo_revisao UNIQUE (numero_do, revisao_numero)
        )
    """)
    op.execute("""
        CREATE INDEX ix_fato_obitos_tempo_local_causa
        ON fato_obitos (dim_tempo_id, dim_local_id, dim_causa_id)
    """)
    op.execute("CREATE INDEX ix_fato_obitos_local ON fato_obitos (dim_local_id)")
    op.execute("CREATE INDEX ix_fato_obitos_causa ON fato_obitos (dim_causa_id)")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS fato_obitos")
