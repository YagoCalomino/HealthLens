"""create fato_notificacoes

Revision ID: 0018
Revises: 0017
Create Date: 2026-07-27

SINAN star-schema fact table. One row per notification. The
counting column is deliberately named `notificacoes`, not `casos` — SINAN
has no reliable dedup key across the 3 agravos, so this table is an append-only notification log, never
an asserted-confirmed-case count.

Agravo-specific columns are nullable and split as follows (live-verified):
  - classi_fin: raw DataSUS code, populated for DENG/CHIK only — the
    CLASSI_FIN column does not exist at all in ANIM's source data.
  - gravidade_grave: derived from the 15-member GRAV_* boolean family,
    which exists only for DENG/CHIK.
  - tra_classi / tp_acidente: raw ANIM-only severity/accident-type codes;
    NULL for DENG/CHIK.
"""

from typing import Sequence, Union

from alembic import op

revision: str = "0018"
down_revision: Union[str, None] = "0017"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE fato_notificacoes (
            id                  BIGINT PRIMARY KEY GENERATED ALWAYS AS IDENTITY,
            dim_tempo_id        INTEGER NOT NULL REFERENCES dim_tempo(id),
            dim_local_id        INTEGER NOT NULL REFERENCES dim_local(id),
            dim_agravo_id       INTEGER NOT NULL REFERENCES dim_agravo(id),
            dim_faixa_etaria_id INTEGER NOT NULL REFERENCES dim_faixa_etaria(id),
            tipo_agravo         VARCHAR(10) NOT NULL,
            numero_notificacao  VARCHAR(40) NOT NULL,
            notificacoes        INTEGER NOT NULL DEFAULT 1,
            taxa_por_100k       NUMERIC(10, 4),
            sexo                CHAR(1),
            idade_anos          SMALLINT,
            classi_fin          SMALLINT,
            gravidade_grave     BOOLEAN,
            tra_classi          SMALLINT,
            tp_acidente         SMALLINT,
            CONSTRAINT uq_fato_notificacoes_numero_agravo UNIQUE (numero_notificacao, tipo_agravo)
        )
    """)
    op.execute("""
        CREATE INDEX ix_fato_notificacoes_tempo_local_agravo
        ON fato_notificacoes (dim_tempo_id, dim_local_id, dim_agravo_id)
    """)
    op.execute(
        "CREATE INDEX ix_fato_notificacoes_local ON fato_notificacoes (dim_local_id)"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS fato_notificacoes")
