import psycopg2, os

conn = psycopg2.connect(os.environ['DATABASE_URL_SYNC'])
conn.autocommit = True
cur = conn.cursor()

# Top tables por tamanho
cur.execute("""
    SELECT relname, pg_size_pretty(pg_total_relation_size(oid)) AS total,
           pg_total_relation_size(oid) AS bytes
    FROM pg_class WHERE relkind='r' AND relnamespace='public'::regnamespace
    ORDER BY bytes DESC LIMIT 15
""")
print("Tabelas maiores ANTES do VACUUM:")
for r in cur.fetchall():
    print(f"  {r[0]}: {r[1]}")

cur.execute("SELECT pg_size_pretty(pg_database_size(current_database()))")
print(f"\nDB size antes: {cur.fetchone()[0]}")

# VACUUM FULL nas tabelas mais pesadas
heavy = [
    "fato_notificacoes",
    "mv_curva_epidemica_municipio_semana",
    "mv_curva_epidemica_semana",
    "mv_curva_epidemica",
    "dim_local",
    "dim_populacao",
]
for t in heavy:
    print(f"VACUUM FULL {t}...", end=" ", flush=True)
    cur.execute(f"VACUUM FULL ANALYZE {t}")
    print("ok")

cur.execute("SELECT pg_size_pretty(pg_database_size(current_database()))")
print(f"\nDB size depois: {cur.fetchone()[0]}")

cur.execute("""
    SELECT relname, pg_size_pretty(pg_total_relation_size(oid)) AS total
    FROM pg_class WHERE relkind='r' AND relnamespace='public'::regnamespace
    ORDER BY pg_total_relation_size(oid) DESC LIMIT 10
""")
print("\nTabelas maiores DEPOIS:")
for r in cur.fetchall():
    print(f"  {r[0]}: {r[1]}")
