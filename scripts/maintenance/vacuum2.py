import psycopg2, os

conn = psycopg2.connect(os.environ['DATABASE_URL_SYNC'])
conn.autocommit = True
cur = conn.cursor()

for t in ["fato_internacoes", "fato_obitos", "mv_taxa_municipio_ano", "mv_breakdown_anual", "mv_uf_summary_anual", "mv_taxa_uf_ano", "forecast_resultados"]:
    print(f"VACUUM FULL {t}...", end=" ", flush=True)
    cur.execute(f"VACUUM FULL ANALYZE {t}")
    print("ok")

cur.execute("SELECT pg_size_pretty(pg_database_size(current_database()))")
print(f"\nDB size final: {cur.fetchone()[0]}")
