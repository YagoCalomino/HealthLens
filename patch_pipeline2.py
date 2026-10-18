with open("backend/etl/pipeline.py", "r", encoding="utf-8") as f:
    src = f.read()

old = (
    "    logger.info(\"Refreshing aggregation tables...\")\n"
    "    _orig_ac = conn.autocommit\n"
    "    conn.autocommit = True\n"
    "    cur = conn.cursor()\n"
)
new = (
    "    logger.info(\"Refreshing aggregation tables...\")\n"
    "    _orig_ac = conn.autocommit\n"
    "    conn.autocommit = True\n"
    "    cur = conn.cursor()\n\n"
    "    def _refresh(tname, insert_sql):\n"
    "        cur.execute(\n"
    "            \"SELECT relkind FROM pg_class WHERE relname = %s\", (tname,)\n"
    "        )\n"
    "        row = cur.fetchone()\n"
    "        if row and row[0] == \"m\":\n"
    "            cur.execute(f\"REFRESH MATERIALIZED VIEW {tname}\")\n"
    "        else:\n"
    "            cur.execute(f\"TRUNCATE {tname}\")\n"
    "            cur.execute(insert_sql)\n\n"
)
assert src.count(old) == 1, f"header marker: {src.count(old)}"
src = src.replace(old, new, 1)

tables = [
    "mv_curva_epidemica_semana",
    "mv_curva_epidemica_municipio_semana",
    "mv_uf_summary_anual",
    "mv_breakdown_anual",
    "mv_taxa_uf_ano",
    "mv_taxa_municipio_ano",
]
for t in tables:
    old_t = f"    cur.execute(\"TRUNCATE {t}\")\n    cur.execute(\"\"\""
    new_t = f"    _refresh(\"{t}\", \"\"\""
    count = src.count(old_t)
    assert count == 1, f"{t}: {count} matches"
    src = src.replace(old_t, new_t, 1)

with open("backend/etl/pipeline.py", "w", encoding="utf-8") as f:
    f.write(src)
print("Done!")
