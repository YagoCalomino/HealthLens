"""create audit_ingestao

Revision ID: 0010
Revises: 0009
Create Date: 2026-06-11
"""

from typing import Sequence, Union

from alembic import op

revision: str = "0010"
down_revision: Union[str, None] = "0009"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE audit_ingestao (
            id          BIGINT PRIMARY KEY GENERATED ALWAYS AS IDENTITY,
            arquivo     VARCHAR(200) NOT NULL,
            hash_md5    CHAR(32) NOT NULL,
            uf          CHAR(2) NOT NULL,
            ano         SMALLINT NOT NULL,
            fonte       VARCHAR(3) NOT NULL CHECK (fonte IN ('SIM', 'SIH')),
            ingested_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            CONSTRAINT uq_audit_hash UNIQUE (hash_md5)
        )
    """)
    op.execute("CREATE INDEX ix_audit_ingestao_uf_ano ON audit_ingestao (uf, ano)")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS audit_ingestao")
