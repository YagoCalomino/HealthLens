"""extend municipio_cluster_assignments — add cluster_nome, PCA coords, features_norm

Revision ID: 0013
Revises: 0012
Create Date: 2026-06-12
"""

from typing import Sequence, Union

from alembic import op

revision: str = "0013"
down_revision: Union[str, None] = "0012"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Add cluster label, 2-D PCA coordinates, and normalised feature vector (additive only)
    op.execute("""
        ALTER TABLE municipio_cluster_assignments
            ADD COLUMN IF NOT EXISTS cluster_nome  VARCHAR(100),
            ADD COLUMN IF NOT EXISTS pca_x         NUMERIC(8,4),
            ADD COLUMN IF NOT EXISTS pca_y         NUMERIC(8,4),
            ADD COLUMN IF NOT EXISTS features_norm JSONB
    """)


def downgrade() -> None:
    op.execute("""
        ALTER TABLE municipio_cluster_assignments
            DROP COLUMN IF EXISTS cluster_nome,
            DROP COLUMN IF EXISTS pca_x,
            DROP COLUMN IF EXISTS pca_y,
            DROP COLUMN IF EXISTS features_norm
    """)
