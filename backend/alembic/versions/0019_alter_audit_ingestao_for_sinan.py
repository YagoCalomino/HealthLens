"""alter audit_ingestao for sinan

Revision ID: 0019
Revises: 0018
Create Date: 2026-07-27

Widens audit_ingestao so SINAN's national-grain (agravo, ano) audit rows
can be written. SINAN's sinan() has no state= parameter — every download is
one national file covering all 27 UFs (live-verified by
scripts/spike_pysus_270_sinan.py) — so no UF value
exists at audit-write time.

The pre-existing ix_audit_ingestao_uf_ano index remains valid with NULL uf
values (PostgreSQL B-tree indexes store NULLs), so no index change is
needed. uq_audit_hash UNIQUE (hash_md5) remains the resumability key for
SINAN exactly as it is for SIM/SIH.
"""

from typing import Sequence, Union

from alembic import op

revision: str = "0019"
down_revision: Union[str, None] = "0018"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("""
        ALTER TABLE audit_ingestao ALTER COLUMN uf DROP NOT NULL
    """)
    op.execute("""
        ALTER TABLE audit_ingestao ALTER COLUMN fonte TYPE VARCHAR(5)
    """)
    op.execute("""
        ALTER TABLE audit_ingestao DROP CONSTRAINT IF EXISTS audit_ingestao_fonte_check
    """)
    op.execute("""
        ALTER TABLE audit_ingestao ADD CONSTRAINT ck_audit_ingestao_fonte
        CHECK (fonte IN ('SIM', 'SIH', 'SINAN'))
    """)


def downgrade() -> None:
    op.execute("""
        ALTER TABLE audit_ingestao DROP CONSTRAINT IF EXISTS ck_audit_ingestao_fonte
    """)
    op.execute("""
        DELETE FROM audit_ingestao WHERE fonte = 'SINAN' OR uf IS NULL
    """)
    op.execute("""
        ALTER TABLE audit_ingestao ADD CONSTRAINT audit_ingestao_fonte_check
        CHECK (fonte IN ('SIM', 'SIH'))
    """)
    op.execute("""
        ALTER TABLE audit_ingestao ALTER COLUMN fonte TYPE VARCHAR(3)
    """)
    op.execute("""
        ALTER TABLE audit_ingestao ALTER COLUMN uf SET NOT NULL
    """)
