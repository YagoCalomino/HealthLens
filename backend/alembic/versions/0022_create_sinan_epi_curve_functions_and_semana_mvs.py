"""create sinan epi curve functions and semana mvs

Revision ID: 0022
Revises: 0021
Create Date: 2026-10-07
"""

from alembic import op

revision = "0022"
down_revision = "0021"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # mv_curva_epidemica (base diária — SQL recuperada do pg_matviews)
    op.execute("""
        CREATE MATERIALIZED VIEW IF NOT EXISTS mv_curva_epidemica AS
        WITH pop_ref AS (
            SELECT DISTINCT ON (codigo_ibge_6) codigo_ibge_6, populacao_total
            FROM dim_populacao
            ORDER BY codigo_ibge_6, ano DESC
        )
        SELECT f.dt_notific, f.dim_local_id, f.tipo_agravo AS agravo, l.sigla_uf,
               SUM(f.notificacoes) AS total_notificacoes,
               MAX(p.populacao_total)::numeric AS populacao
        FROM fato_notificacoes f
        JOIN dim_local l ON l.id = f.dim_local_id
        LEFT JOIN pop_ref p ON p.codigo_ibge_6 = l.codigo_ibge_6
        WHERE f.dt_notific IS NOT NULL
        GROUP BY f.dt_notific, f.dim_local_id, f.tipo_agravo, l.sigla_uf;
    """)
    # Funções semana epidemiológica DataSUS/MMWR
    op.execute(
        "CREATE OR REPLACE FUNCTION fn_week_sunday(dt date) RETURNS date LANGUAGE sql IMMUTABLE STRICT AS $$ SELECT (dt - EXTRACT(DOW FROM dt)::int)::date; $$;"
    )
    op.execute(
        "CREATE OR REPLACE FUNCTION fn_epi_year(dt date) RETURNS integer LANGUAGE sql IMMUTABLE STRICT AS $$ SELECT EXTRACT(YEAR FROM fn_week_sunday(dt) + 3)::int; $$;"
    )
    op.execute(
        "CREATE OR REPLACE FUNCTION fn_week1_sunday(yr int) RETURNS date LANGUAGE sql IMMUTABLE STRICT AS $$ SELECT (make_date(yr, 1, 4) - EXTRACT(DOW FROM make_date(yr, 1, 4))::int)::date; $$;"
    )
    op.execute(
        "CREATE OR REPLACE FUNCTION fn_epi_week(dt date) RETURNS integer LANGUAGE sql IMMUTABLE STRICT AS $$ SELECT (fn_week_sunday(dt) - fn_week1_sunday(fn_epi_year(dt))) / 7 + 1; $$;"
    )
    # mv_curva_epidemica_semana
    op.execute("""
        CREATE MATERIALIZED VIEW IF NOT EXISTS mv_curva_epidemica_semana AS
        SELECT agravo, sigla_uf, epi_year AS ano_epidemiologico, epi_week AS semana_epidemiologica,
               SUM(total_notificacoes) AS total_notificacoes, SUM(pop_municipio) AS total_populacao
        FROM (
            SELECT agravo, sigla_uf, dim_local_id,
                   fn_epi_year(dt_notific) AS epi_year, fn_epi_week(dt_notific) AS epi_week,
                   SUM(total_notificacoes) AS total_notificacoes, MAX(populacao) AS pop_municipio
            FROM mv_curva_epidemica WHERE dt_notific IS NOT NULL
            GROUP BY agravo, sigla_uf, dim_local_id, fn_epi_year(dt_notific), fn_epi_week(dt_notific)
        ) t
        GROUP BY agravo, sigla_uf, epi_year, epi_week WITH DATA;
    """)
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_mv_curva_semana_lookup ON mv_curva_epidemica_semana (agravo, sigla_uf, ano_epidemiologico, semana_epidemiologica);"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_mv_curva_semana_agravo ON mv_curva_epidemica_semana (agravo, ano_epidemiologico, semana_epidemiologica);"
    )
    # mv_curva_epidemica_municipio_semana
    op.execute("""
        CREATE MATERIALIZED VIEW IF NOT EXISTS mv_curva_epidemica_municipio_semana AS
        SELECT agravo, sigla_uf, dim_local_id,
               fn_epi_year(dt_notific) AS ano_epidemiologico, fn_epi_week(dt_notific) AS semana_epidemiologica,
               SUM(total_notificacoes) AS total_notificacoes, MAX(populacao) AS total_populacao
        FROM mv_curva_epidemica WHERE dt_notific IS NOT NULL
        GROUP BY agravo, sigla_uf, dim_local_id, fn_epi_year(dt_notific), fn_epi_week(dt_notific)
        WITH DATA;
    """)
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_mv_curva_mun_semana_lookup ON mv_curva_epidemica_municipio_semana (agravo, dim_local_id, ano_epidemiologico, semana_epidemiologica);"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_mv_curva_mun_semana_agravo_uf ON mv_curva_epidemica_municipio_semana (agravo, sigla_uf, ano_epidemiologico, semana_epidemiologica);"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_mv_mun_semana_agravo_uf ON mv_curva_epidemica_municipio_semana (agravo, sigla_uf, dim_local_id, ano_epidemiologico);"
    )


def downgrade() -> None:
    op.execute(
        "DROP MATERIALIZED VIEW IF EXISTS mv_curva_epidemica_municipio_semana CASCADE;"
    )
    op.execute("DROP MATERIALIZED VIEW IF EXISTS mv_curva_epidemica_semana CASCADE;")
    op.execute("DROP MATERIALIZED VIEW IF EXISTS mv_curva_epidemica CASCADE;")
    op.execute("DROP FUNCTION IF EXISTS fn_epi_week(date);")
    op.execute("DROP FUNCTION IF EXISTS fn_week1_sunday(int);")
    op.execute("DROP FUNCTION IF EXISTS fn_epi_year(date);")
    op.execute("DROP FUNCTION IF EXISTS fn_week_sunday(date);")
