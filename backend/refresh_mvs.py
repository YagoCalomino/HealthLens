import os
import time
import psycopg2

conn = psycopg2.connect(os.environ["DATABASE_URL_SYNC"])
conn.autocommit = True
cur = conn.cursor()


def step(label, sql):
    print(f"  {label}...", end=" ", flush=True)
    t = time.time()
    cur.execute(sql)
    print(f"{cur.rowcount} rows ({time.time() - t:.1f}s)")


print("Refreshing aggregation tables...")

cur.execute("TRUNCATE mv_curva_epidemica_semana")
step(
    "mv_curva_epidemica_semana",
    """
    INSERT INTO mv_curva_epidemica_semana
    WITH pop_ref AS (
        SELECT DISTINCT ON (codigo_ibge_6) codigo_ibge_6, populacao_total
        FROM dim_populacao ORDER BY codigo_ibge_6, ano DESC
    ),
    mun_week AS (
        SELECT f.tipo_agravo AS agravo, l.sigla_uf, f.dim_local_id,
               fn_epi_year(f.dt_notific) AS epi_year,
               fn_epi_week(f.dt_notific) AS epi_week,
               SUM(f.notificacoes) AS total_notificacoes,
               MAX(p.populacao_total)::numeric AS pop_municipio
        FROM fato_notificacoes f
        JOIN dim_local l ON l.id = f.dim_local_id
        LEFT JOIN pop_ref p ON p.codigo_ibge_6 = l.codigo_ibge_6
        WHERE f.dt_notific IS NOT NULL
        GROUP BY f.tipo_agravo, l.sigla_uf, f.dim_local_id,
                 fn_epi_year(f.dt_notific), fn_epi_week(f.dt_notific)
    )
    SELECT agravo, sigla_uf, epi_year AS ano_epidemiologico,
           epi_week AS semana_epidemiologica,
           SUM(total_notificacoes) AS total_notificacoes,
           SUM(pop_municipio) AS total_populacao
    FROM mun_week GROUP BY agravo, sigla_uf, epi_year, epi_week
""",
)

cur.execute("TRUNCATE mv_curva_epidemica_municipio_semana")
step(
    "mv_curva_epidemica_municipio_semana",
    """
    INSERT INTO mv_curva_epidemica_municipio_semana
    WITH pop_ref AS (
        SELECT DISTINCT ON (codigo_ibge_6) codigo_ibge_6, populacao_total
        FROM dim_populacao ORDER BY codigo_ibge_6, ano DESC
    )
    SELECT f.tipo_agravo AS agravo, l.sigla_uf, f.dim_local_id,
           fn_epi_year(f.dt_notific) AS ano_epidemiologico,
           fn_epi_week(f.dt_notific) AS semana_epidemiologica,
           SUM(f.notificacoes) AS total_notificacoes,
           MAX(p.populacao_total)::numeric AS total_populacao
    FROM fato_notificacoes f
    JOIN dim_local l ON l.id = f.dim_local_id
    LEFT JOIN pop_ref p ON p.codigo_ibge_6 = l.codigo_ibge_6
    WHERE f.dt_notific IS NOT NULL
    GROUP BY f.tipo_agravo, l.sigla_uf, f.dim_local_id,
             fn_epi_year(f.dt_notific), fn_epi_week(f.dt_notific)
""",
)

cur.execute("TRUNCATE mv_uf_summary_anual")
step(
    "mv_uf_summary_anual",
    """
    INSERT INTO mv_uf_summary_anual
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
    GROUP BY agravo, sigla_uf, ano_epidemiologico
""",
)

cur.execute("SELECT pg_size_pretty(pg_database_size(current_database()))")
print(f"\nDB size: {cur.fetchone()[0]}")
print("Done!")
cur.close()
conn.close()
