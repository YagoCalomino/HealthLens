import psycopg2, os, time

conn = psycopg2.connect(os.environ['DATABASE_URL_SYNC'])
conn.autocommit = True
cur = conn.cursor()

base = "tmp_all/tmp"

def restore(table, csv_file):
    path = f"{base}/{csv_file}"
    print(f"Restaurando {table}...", end=" ", flush=True)
    t = time.time()
    cur.execute(f"TRUNCATE {table}")
    with open(path, 'r', encoding='utf-8') as f:
        cur.copy_expert(f"COPY {table} FROM STDIN CSV HEADER", f)
    cur.execute(f"SELECT COUNT(*) FROM {table}")
    print(f"{cur.fetchone()[0]} rows  ({time.time()-t:.1f}s)")

# Sem mv_curva_epidemica (74MB CSV = ~134MB DB) para economizar espaco
restore("mv_curva_epidemica_semana",           "mv_curva_epidemica_semana.csv")
restore("mv_curva_epidemica_municipio_semana", "mv_municipio_semana.csv")
restore("mv_uf_summary_anual",                 "mv_uf_summary.csv")
restore("mv_breakdown_anual",                  "mv_breakdown.csv")
restore("mv_taxa_uf_ano",                      "mv_taxa_uf.csv")
restore("mv_taxa_municipio_ano",               "mv_taxa_municipio.csv")

cur.execute("SELECT pg_size_pretty(pg_database_size(current_database()))")
print("DB size:", cur.fetchone()[0])
cur.close()
conn.close()
