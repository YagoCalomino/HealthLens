"""create dim_agravo

Revision ID: 0017
Revises: 0016
Create Date: 2026-07-27
"""

from typing import Sequence, Union

from alembic import op

revision: str = "0017"
down_revision: Union[str, None] = "0016"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE dim_agravo (
            id         INTEGER PRIMARY KEY GENERATED ALWAYS AS IDENTITY,
            codigo     VARCHAR(10) NOT NULL,
            descricao  VARCHAR(50) NOT NULL,
            CONSTRAINT uq_dim_agravo_codigo UNIQUE (codigo)
        )
    """)
    # Inline 3-row seed — deliberate choice for this closed 3-row set.
    # Unlike dim_faixa_etaria/CID-10/IBGE/TCU (large external catalogs seeded
    # via backend/seeds/), dim_agravo's set is closed (DENG/CHIK/ANIM) and
    # small enough that an inline INSERT in the migration itself is simpler
    # than a separate seed script. Codes are UPPERCASE, matching pysus's own
    # Literal values so tipo_agravo round-trips into
    # pysus.sinan(disease=...) without case normalization.
    op.execute("""
        INSERT INTO dim_agravo (codigo, descricao) VALUES
            ('DENG', 'Dengue'),
            ('CHIK', 'Chikungunya'),
            ('ANIM', 'Animais peçonhentos')
    """)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS dim_agravo")
