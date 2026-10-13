"""create dim_local

Revision ID: 0002
Revises: 0001
Create Date: 2026-06-11
"""

# Both IBGE codes mandatory: codigo_ibge_6 is the DataSUS FK, codigo_ibge_7 (with check digit) matches TopoJSON
from typing import Sequence, Union

from alembic import op

revision: str = "0002"
down_revision: Union[str, None] = "0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE dim_local (
            id               INTEGER PRIMARY KEY GENERATED ALWAYS AS IDENTITY,
            codigo_ibge_6    CHAR(6) NOT NULL,
            codigo_ibge_7    CHAR(7) NOT NULL,
            nome_municipio   VARCHAR(100) NOT NULL,
            nome_uf          VARCHAR(50) NOT NULL,
            sigla_uf         CHAR(2) NOT NULL,
            codigo_uf        CHAR(2) NOT NULL,
            regiao           VARCHAR(20) NOT NULL,
            valid_from       DATE NOT NULL,
            is_current       BOOLEAN NOT NULL DEFAULT TRUE,
            ativo            BOOLEAN NOT NULL DEFAULT TRUE,
            codigo_sucessor  CHAR(6),
            CONSTRAINT uq_dim_local_ibge6_valid_from UNIQUE (codigo_ibge_6, valid_from),
            CONSTRAINT chk_dim_local_ibge7_not_null CHECK (codigo_ibge_7 IS NOT NULL)
        )
    """)
    op.execute("CREATE INDEX ix_dim_local_ibge6 ON dim_local (codigo_ibge_6)")
    op.execute("CREATE INDEX ix_dim_local_ibge7 ON dim_local (codigo_ibge_7)")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS dim_local")
