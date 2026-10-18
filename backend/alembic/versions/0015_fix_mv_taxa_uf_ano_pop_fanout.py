"""fix mv_taxa_uf_ano population fan-out via dim_local natural key join

The original pop_uf CTE joined dim_populacao to dim_local on the natural key
(codigo_ibge_6) with is_current=TRUE. If dim_local contains more than one
is_current=TRUE row per codigo_ibge_6 (SCD-2 edge case or loader re-runs),
each dim_populacao row fans out to N dim_local rows, inflating SUM(populacao_total)
by N for every (sigla_uf, ano) group.

Fix: introduce a uf_lookup CTE that uses DISTINCT ON (codigo_ibge_6) to
guarantee exactly one sigla_uf per municipality code before the population
aggregate join.

Revision ID: 0015
Revises: 0014
Create Date: 2026-06-16
"""

from typing import Sequence, Union

from alembic import op

revision: str = "0015"
down_revision: Union[str, None] = "0014"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Drop and recreate — MATERIALIZED VIEW cannot be altered, only replaced.
    # DROP cascades to the unique index automatically.
    op.execute("DROP MATERIALIZED VIEW IF EXISTS mv_taxa_uf_ano")

    op.execute("""
        CREATE MATERIALIZED VIEW mv_taxa_uf_ano AS
        WITH uf_lookup AS (
            SELECT DISTINCT ON (codigo_ibge_6) codigo_ibge_6, sigla_uf
            FROM dim_local
            WHERE is_current = TRUE
            ORDER BY codigo_ibge_6
        ),
        pop_uf AS (
            SELECT ul.sigla_uf, dp.ano, SUM(dp.populacao_total) AS populacao_uf
            FROM dim_populacao dp
            JOIN uf_lookup ul ON dp.codigo_ibge_6 = ul.codigo_ibge_6
            GROUP BY ul.sigla_uf, dp.ano
        ),
        obitos_uf AS (
            SELECT dl.sigla_uf, dt.ano, SUM(fo.obitos) AS total_eventos
            FROM fato_obitos fo
            JOIN dim_tempo dt ON fo.dim_tempo_id = dt.id
            JOIN dim_local dl ON fo.dim_local_id = dl.id
            GROUP BY dl.sigla_uf, dt.ano
        ),
        internacoes_uf AS (
            SELECT dl.sigla_uf, dt.ano, SUM(fi.internacoes) AS total_eventos
            FROM fato_internacoes fi
            JOIN dim_tempo dt ON fi.dim_tempo_id = dt.id
            JOIN dim_local dl ON fi.dim_local_id = dl.id
            GROUP BY dl.sigla_uf, dt.ano
        )
        SELECT o.sigla_uf, o.ano, o.total_eventos, p.populacao_uf,
               o.total_eventos * 100000.0 / NULLIF(p.populacao_uf, 0) AS taxa_por_100k,
               'SIM'::VARCHAR(3) AS fonte
        FROM obitos_uf o
        JOIN pop_uf p ON o.sigla_uf = p.sigla_uf AND o.ano = p.ano
        UNION ALL
        SELECT i.sigla_uf, i.ano, i.total_eventos, p.populacao_uf,
               i.total_eventos * 100000.0 / NULLIF(p.populacao_uf, 0) AS taxa_por_100k,
               'SIH'::VARCHAR(3) AS fonte
        FROM internacoes_uf i
        JOIN pop_uf p ON i.sigla_uf = p.sigla_uf AND i.ano = p.ano
        WITH DATA
    """)

    op.execute(
        "CREATE UNIQUE INDEX uq_mv_taxa_uf_ano ON mv_taxa_uf_ano (sigla_uf, ano, fonte)"
    )


def downgrade() -> None:
    op.execute("DROP MATERIALIZED VIEW IF EXISTS mv_taxa_uf_ano")

    op.execute("""
        CREATE MATERIALIZED VIEW mv_taxa_uf_ano AS
        WITH pop_uf AS (
            SELECT dl.sigla_uf, dp.ano, SUM(dp.populacao_total) AS populacao_uf
            FROM dim_populacao dp
            JOIN dim_local dl ON dp.codigo_ibge_6 = dl.codigo_ibge_6 AND dl.is_current = TRUE
            GROUP BY dl.sigla_uf, dp.ano
        ),
        obitos_uf AS (
            SELECT dl.sigla_uf, dt.ano, SUM(fo.obitos) AS total_eventos
            FROM fato_obitos fo
            JOIN dim_tempo dt ON fo.dim_tempo_id = dt.id
            JOIN dim_local dl ON fo.dim_local_id = dl.id
            GROUP BY dl.sigla_uf, dt.ano
        ),
        internacoes_uf AS (
            SELECT dl.sigla_uf, dt.ano, SUM(fi.internacoes) AS total_eventos
            FROM fato_internacoes fi
            JOIN dim_tempo dt ON fi.dim_tempo_id = dt.id
            JOIN dim_local dl ON fi.dim_local_id = dl.id
            GROUP BY dl.sigla_uf, dt.ano
        )
        SELECT o.sigla_uf, o.ano, o.total_eventos, p.populacao_uf,
               o.total_eventos * 100000.0 / NULLIF(p.populacao_uf, 0) AS taxa_por_100k,
               'SIM'::VARCHAR(3) AS fonte
        FROM obitos_uf o
        JOIN pop_uf p ON o.sigla_uf = p.sigla_uf AND o.ano = p.ano
        UNION ALL
        SELECT i.sigla_uf, i.ano, i.total_eventos, p.populacao_uf,
               i.total_eventos * 100000.0 / NULLIF(p.populacao_uf, 0) AS taxa_por_100k,
               'SIH'::VARCHAR(3) AS fonte
        FROM internacoes_uf i
        JOIN pop_uf p ON i.sigla_uf = p.sigla_uf AND i.ano = p.ano
        WITH DATA
    """)

    op.execute(
        "CREATE UNIQUE INDEX uq_mv_taxa_uf_ano ON mv_taxa_uf_ano (sigla_uf, ano, fonte)"
    )
