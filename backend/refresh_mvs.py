import os

import psycopg2

DATABASE_URL = os.environ["DATABASE_URL_SYNC"]

conn = psycopg2.connect(DATABASE_URL)
conn.autocommit = True
cur = conn.cursor()

print("Refreshing MV chain...")
for mv in [
    "mv_curva_epidemica",
    "mv_curva_epidemica_semana",
    "mv_curva_epidemica_municipio_semana",
    "mv_uf_summary_anual",
]:
    print(f"  REFRESH {mv}...", end=" ", flush=True)
    cur.execute(f"REFRESH MATERIALIZED VIEW {mv}")
    print("ok")

cur.execute("""
    SELECT agravo, total_notificacoes * 100000.0 / NULLIF(total_populacao, 0) AS taxa_100k
    FROM mv_uf_summary_anual
    WHERE sigla_uf = 'SP' AND ano = 2023
    ORDER BY agravo
""")
print("\nSP 2023 taxa por 100k:")
for r in cur.fetchall():
    print(f"  {r[0]}: {r[1]:.1f}")

conn.close()
