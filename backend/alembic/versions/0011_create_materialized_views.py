"""create materialized views mv_taxa_uf_ano and mv_taxa_municipio_ano

Revision ID: 0011
Revises: 0010
Create Date: 2026-06-11
"""

from typing import Sequence, Union

from alembic import op

revision: str = "0011"
down_revision: Union[str, None] = "0010"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
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

    op.execute("""
        CREATE MATERIALIZED VIEW mv_taxa_municipio_ano AS
        WITH obitos_mun AS (
            SELECT dl.codigo_ibge_6, dl.codigo_ibge_7, dl.nome_municipio, dl.sigla_uf, dl.regiao,
                   dt.ano, SUM(fo.obitos) AS total_eventos
            FROM fato_obitos fo
            JOIN dim_tempo dt ON fo.dim_tempo_id = dt.id
            JOIN dim_local dl ON fo.dim_local_id = dl.id
            GROUP BY dl.codigo_ibge_6, dl.codigo_ibge_7, dl.nome_municipio, dl.sigla_uf, dl.regiao, dt.ano
        ),
        internacoes_mun AS (
            SELECT dl.codigo_ibge_6, dl.codigo_ibge_7, dl.nome_municipio, dl.sigla_uf, dl.regiao,
                   dt.ano, SUM(fi.internacoes) AS total_eventos
            FROM fato_internacoes fi
            JOIN dim_tempo dt ON fi.dim_tempo_id = dt.id
            JOIN dim_local dl ON fi.dim_local_id = dl.id
            GROUP BY dl.codigo_ibge_6, dl.codigo_ibge_7, dl.nome_municipio, dl.sigla_uf, dl.regiao, dt.ano
        )
        SELECT o.codigo_ibge_6, o.codigo_ibge_7, o.nome_municipio, o.sigla_uf, o.regiao,
               o.ano, o.total_eventos, dp.populacao_total AS populacao_municipio,
               o.total_eventos * 100000.0 / NULLIF(dp.populacao_total, 0) AS taxa_por_100k,
               'SIM'::VARCHAR(3) AS fonte
        FROM obitos_mun o
        LEFT JOIN dim_populacao dp ON o.codigo_ibge_6 = dp.codigo_ibge_6 AND o.ano = dp.ano
        UNION ALL
        SELECT i.codigo_ibge_6, i.codigo_ibge_7, i.nome_municipio, i.sigla_uf, i.regiao,
               i.ano, i.total_eventos, dp.populacao_total AS populacao_municipio,
               i.total_eventos * 100000.0 / NULLIF(dp.populacao_total, 0) AS taxa_por_100k,
               'SIH'::VARCHAR(3) AS fonte
        FROM internacoes_mun i
        LEFT JOIN dim_populacao dp ON i.codigo_ibge_6 = dp.codigo_ibge_6 AND i.ano = dp.ano
        WITH DATA
    """)

    op.execute(
        "CREATE UNIQUE INDEX uq_mv_taxa_municipio_ano ON mv_taxa_municipio_ano (codigo_ibge_6, ano, fonte)"
    )


def downgrade() -> None:
    op.execute("DROP MATERIALIZED VIEW IF EXISTS mv_taxa_municipio_ano")
    op.execute("DROP MATERIALIZED VIEW IF EXISTS mv_taxa_uf_ano")
