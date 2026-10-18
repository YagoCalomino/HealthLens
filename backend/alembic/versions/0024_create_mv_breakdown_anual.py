"""create mv_breakdown_anual

Revision ID: 0024
Revises: 0023
Create Date: 2026-10-07
"""

from alembic import op

revision = "0024"
down_revision = "0023"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE MATERIALIZED VIEW IF NOT EXISTS mv_breakdown_anual AS
        SELECT da.codigo AS agravo, dl.sigla_uf, dt.ano,
               fn.sexo, fn.classi_fin, fn.gravidade_grave, fn.tra_classi, fn.tp_acidente,
               df.codigo AS faixa_etaria_codigo, df.descricao AS faixa_etaria_descricao,
               df.ordem AS faixa_etaria_ordem,
               SUM(fn.notificacoes) AS total_notificacoes
        FROM fato_notificacoes fn
        JOIN dim_agravo       da ON fn.dim_agravo_id       = da.id
        JOIN dim_local        dl ON fn.dim_local_id        = dl.id
        JOIN dim_tempo        dt ON fn.dim_tempo_id        = dt.id
        JOIN dim_faixa_etaria df ON fn.dim_faixa_etaria_id = df.id
        GROUP BY da.codigo, dl.sigla_uf, dt.ano,
                 fn.sexo, fn.classi_fin, fn.gravidade_grave, fn.tra_classi, fn.tp_acidente,
                 df.codigo, df.descricao, df.ordem;
    """)
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_mv_breakdown_agravo_uf_ano ON mv_breakdown_anual (agravo, sigla_uf, ano);"
    )


def downgrade() -> None:
    op.execute("DROP MATERIALIZED VIEW IF EXISTS mv_breakdown_anual CASCADE;")
