"""create municipio_cluster_assignments

Revision ID: 0009
Revises: 0008
Create Date: 2026-06-11
"""

# ML pre-compute architecture: tables populated offline by ML runner. API is read-only.
from typing import Sequence, Union

from alembic import op

revision: str = "0009"
down_revision: Union[str, None] = "0008"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE municipio_cluster_assignments (
            id                  INTEGER PRIMARY KEY GENERATED ALWAYS AS IDENTITY,
            dim_local_id        INTEGER NOT NULL REFERENCES dim_local(id),
            cluster_id          SMALLINT NOT NULL,
            algoritmo           VARCHAR(30) NOT NULL,
            n_clusters          SMALLINT NOT NULL,
            silhouette_score    NUMERIC(6, 4),
            features_utilizadas TEXT,
            ano_referencia      SMALLINT NOT NULL,
            criado_em           TIMESTAMP NOT NULL DEFAULT now(),
            CONSTRAINT uq_municipio_cluster
                UNIQUE (dim_local_id, algoritmo, n_clusters, ano_referencia)
        )
    """)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS municipio_cluster_assignments")
