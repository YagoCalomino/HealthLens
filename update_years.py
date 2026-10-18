import psycopg2, os, time

conn = psycopg2.connect(os.environ['DATABASE_URL_SYNC'])
conn.autocommit = True
cur = conn.cursor()

anos = (2021, 2022, 2024)

def step(name, sql, params=None):
    print(f"\n[{name}]", flush=True)
    t = time.time()
    cur.execute(sql, params)
    print(f"  {cur.rowcount} rows  ({time.time()-t:.1f}s)")

# --- mv_curva_epidemica_semana ---
step("DELETE semana 2021/2022/2024",
    "DELETE FROM mv_curva_epidemica_semana WHERE ano_epidemiologico = ANY(%s)", (list(anos),))

step("INSERT semana (novo)", """
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
          AND EXTRACT(YEAR FROM f.dt_notific) = ANY(%s)
        GROUP BY f.tipo_agravo, l.sigla_uf, f.dim_local_id,
                 fn_epi_year(f.dt_notific), fn_epi_week(f.dt_notific)
    )
    SELECT agravo, sigla_uf, epi_year AS ano_epidemiologico,
           epi_week AS semana_epidemiologica,
           SUM(total_notificacoes) AS total_notificacoes,
           SUM(pop_municipio) AS total_populacao
    FROM mun_week GROUP BY agravo, sigla_uf, epi_year, epi_week
""", ([2021, 2022, 2024],))

# --- mv_curva_epidemica_municipio_semana ---
step("DELETE municipio_semana 2021/2022/2024",
    "DELETE FROM mv_curva_epidemica_municipio_semana WHERE ano_epidemiologico = ANY(%s)", (list(anos),))

step("INSERT municipio_semana (novo)", """
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
      AND EXTRACT(YEAR FROM f.dt_notific) = ANY(%s)
    GROUP BY f.tipo_agravo, l.sigla_uf, f.dim_local_id,
             fn_epi_year(f.dt_notific), fn_epi_week(f.dt_notific)
""", ([2021, 2022, 2024],))

cur.execute("SELECT pg_size_pretty(pg_database_size(current_database()))")
print(f"\nDB size: {cur.fetchone()[0]}")

# Verificar resultado
cur.execute("""
    SELECT agravo, ano_epidemiologico, COUNT(*) as semanas
    FROM mv_curva_epidemica_semana
    GROUP BY agravo, ano_epidemiologico ORDER BY agravo, ano_epidemiologico
""")
print("\nResumo final mv_curva_epidemica_semana:")
for r in cur.fetchall():
    print(f"  {r[0]} {r[1]}: {r[2]} semanas")

cur.close()
conn.close()
