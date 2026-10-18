"""create mv_uf_summary_anual

Revision ID: 0023
Revises: 0022
Create Date: 2026-10-07
"""

from alembic import op

revision = "0023"
down_revision = "0022"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE MATERIALIZED VIEW IF NOT EXISTS mv_uf_summary_anual AS
        SELECT agravo, sigla_uf, ano_epidemiologico AS ano,
               SUM(total_notificacoes) AS total_notificacoes,
               SUM(max_populacao) AS total_populacao
        FROM (
            SELECT agravo, sigla_uf, dim_local_id, ano_epidemiologico,
                   SUM(total_notificacoes) AS total_notificacoes,
                   MAX(total_populacao) AS max_populacao
            FROM mv_curva_epidemica_municipio_semana
            GROUP BY agravo, sigla_uf, dim_local_id, ano_epidemiologico
        ) muni_annual
        GROUP BY agravo, sigla_uf, ano_epidemiologico;
    """)
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_mv_uf_summary_anual ON mv_uf_summary_anual (agravo, sigla_uf, ano);"
    )


def downgrade() -> None:
    op.execute("DROP MATERIALIZED VIEW IF EXISTS mv_uf_summary_anual CASCADE;")
