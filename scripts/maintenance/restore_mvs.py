import psycopg2, os

conn = psycopg2.connect(os.environ['DATABASE_URL_SYNC'])
conn.autocommit = True
cur = conn.cursor()

def restore(table, csv_path):
    print(f"Restaurando {table}...", end=" ", flush=True)
    cur.execute(f"TRUNCATE {table}")
    with open(csv_path, 'r', encoding='utf-8') as f:
        cur.copy_expert(f"COPY {table} FROM STDIN CSV HEADER", f)
    cur.execute(f"SELECT COUNT(*) FROM {table}")
    print(f"{cur.fetchone()[0]} rows")

restore("mv_curva_epidemica",                 "tmp/mv_curva_epidemica.csv")
restore("mv_curva_epidemica_semana",          "tmp/mv_curva_epidemica_semana.csv")
restore("mv_curva_epidemica_municipio_semana","tmp/mv_municipio_semana.csv")
restore("mv_uf_summary_anual",                "tmp/mv_uf_summary.csv")
restore("mv_breakdown_anual",                 "tmp/mv_breakdown.csv")
restore("mv_taxa_uf_ano",                     "tmp/mv_taxa_uf.csv")
restore("mv_taxa_municipio_ano",              "tmp/mv_taxa_municipio.csv")

cur.execute("SELECT pg_size_pretty(pg_database_size(current_database()))")
print("DB size:", cur.fetchone()[0])
print("Concluido!")
cur.close()
conn.close()
