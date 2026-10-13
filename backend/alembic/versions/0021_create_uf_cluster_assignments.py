"""create uf_cluster_assignments

Revision ID: 0021
Revises: 0020
Create Date: 2026-08-12

ML pre-compute architecture: tables populated offline by ML runner. API is
read-only. Genuinely UF-grain clustering (KMeans + PCA run on 27 UF-level
feature rows), not an average of municipio_cluster_assignments' per-municipio
PCA coordinates — averaging pca_y across municipios collapsed it toward the
(mean-zero, by PCA construction) global mean for every UF, producing a
flat-line scatter. A dedicated UF-grain run produces genuine 2D
variance because it decomposes UF-level (not municipio-level) variance.
"""

from typing import Sequence, Union

from alembic import op

revision: str = "0021"
down_revision: Union[str, None] = "0020"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE uf_cluster_assignments (
            id                  INTEGER PRIMARY KEY GENERATED ALWAYS AS IDENTITY,
            sigla_uf            VARCHAR(2) NOT NULL,
            cluster_id          SMALLINT NOT NULL,
            algoritmo           VARCHAR(30) NOT NULL,
            n_clusters          SMALLINT NOT NULL,
            silhouette_score    NUMERIC(6, 4),
            features_utilizadas TEXT,
            ano_referencia      SMALLINT NOT NULL,
            cluster_nome        VARCHAR(100),
            pca_x               NUMERIC(8, 4),
            pca_y               NUMERIC(8, 4),
            n_municipios        SMALLINT NOT NULL,
            features_norm       JSON,
            criado_em           TIMESTAMP NOT NULL DEFAULT now(),
            CONSTRAINT uq_uf_cluster
                UNIQUE (sigla_uf, algoritmo, n_clusters, ano_referencia)
        )
    """)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS uf_cluster_assignments")
