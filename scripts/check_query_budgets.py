"""Query-time budget check for the 5 dashboard queries.

Stdlib + psycopg2 only — mirrors `validate_env.py`'s shape. Runs
`EXPLAIN (ANALYZE, FORMAT JSON)` for each of the 5 queries the dashboard actually
issues against a real Postgres instance and asserts each stays under a uniform
200ms budget (matching the `/indicadores` p50 < 200ms target).

This is intentionally NOT part of the pytest suite — it is invoked
directly (e.g. `python scripts/check_query_budgets.py`) against a seeded
Postgres database. CI runs it in the query-budgets job.

Budgets are evaluated against whatever sample-data volume exists in the target
database. In this project's seeded sample data, SIH is limited to ~1,084 rows
— do not assume full-scale DataSUS volume when
interpreting timings.
"""
import os
import sys

import psycopg2

BUDGET_MS = 200

# Representative bound parameters — present in the tracked sample data
# (data/sample/sih_sample.parquet, data/sample/sim_sample.parquet).
UF_SAMPLE = "SP"
MUNICIPIO_SAMPLE = "350300"  # MUNIC_RES/CODMUNRES value seen in sample data (state code 35 = SP)
ANO_INICIO_SAMPLE = 2019
ANO_FIM_SAMPLE = 2023
METRICA_SAMPLE = "taxa_mortalidade_100k"
ALGORITMO_SAMPLE = "KMeans"

# (name, sql, params) — mirrors the router `select()` filter/order construction.
QUERIES: list[tuple[str, str, dict]] = [
    (
        "choropleth (UF summary)",
        """
        SELECT sigla_uf, ano, total_eventos, populacao_uf, taxa_por_100k, fonte
        FROM mv_taxa_uf_ano
        WHERE sigla_uf = %(uf)s
        ORDER BY sigla_uf, ano, fonte
        """,
        {"uf": UF_SAMPLE},
    ),
    (
        "drill-down (municipios by UF)",
        """
        SELECT
            dl.codigo_ibge_6,
            dl.nome_municipio,
            dl.sigla_uf,
            dl.codigo_ibge_7,
            EXISTS (
                SELECT 1 FROM mv_taxa_municipio_ano mv
                WHERE mv.codigo_ibge_6 = dl.codigo_ibge_6
            ) AS tem_dados
        FROM dim_local dl
        WHERE dl.sigla_uf = %(uf)s AND dl.is_current = true
        ORDER BY dl.nome_municipio
        """,
        {"uf": UF_SAMPLE},
    ),
    (
        "indicator time series (mv_taxa_uf_ano, ano range)",
        """
        SELECT sigla_uf, ano, total_eventos, taxa_por_100k, fonte
        FROM mv_taxa_uf_ano
        WHERE ano BETWEEN %(ano_inicio)s AND %(ano_fim)s
        ORDER BY sigla_uf, ano, fonte
        """,
        {"ano_inicio": ANO_INICIO_SAMPLE, "ano_fim": ANO_FIM_SAMPLE},
    ),
    (
        "forecast fetch (one municipio)",
        """
        SELECT
            fr.granularidade,
            fr.ano_forecast,
            fr.valor_previsto,
            fr.intervalo_inferior_80,
            fr.intervalo_superior_80,
            fr.intervalo_inferior_95,
            fr.intervalo_superior_95,
            fr.mase,
            fr.smape,
            fr.modelo_utilizado,
            fr.ano_referencia
        FROM forecast_resultados fr
        JOIN dim_local dl ON fr.dim_local_id = dl.id
        WHERE dl.codigo_ibge_6 = %(municipio)s
          AND fr.granularidade = 'municipio'
          AND fr.metrica = %(metrica)s
          AND fr.dim_causa_id IS NULL
        ORDER BY fr.modelo_utilizado, fr.ano_forecast
        """,
        {"municipio": MUNICIPIO_SAMPLE, "metrica": METRICA_SAMPLE},
    ),
    (
        "cluster assignment",
        """
        SELECT
            dl.codigo_ibge_6,
            dl.codigo_ibge_7,
            dl.nome_municipio,
            dl.sigla_uf,
            mca.cluster_id,
            mca.cluster_nome,
            mca.pca_x,
            mca.pca_y,
            mca.silhouette_score,
            mca.ano_referencia
        FROM municipio_cluster_assignments mca
        JOIN dim_local dl ON mca.dim_local_id = dl.id
        WHERE mca.algoritmo = %(algoritmo)s AND dl.is_current = true
        ORDER BY dl.sigla_uf, dl.nome_municipio
        """,
        {"algoritmo": ALGORITMO_SAMPLE},
    ),
]


def run_query_budgets() -> int:
    dsn = os.environ.get("DATABASE_URL_SYNC", "")
    if not dsn:
        print("Query budget check FAILED:")
        print("  Missing: DATABASE_URL_SYNC")
        return 1

    # DATABASE_URL_SYNC carries the SQLAlchemy `+psycopg2` dialect suffix
    # (postgresql+psycopg2://...); psycopg2.connect() needs the plain scheme.
    dsn = dsn.replace("postgresql+psycopg2://", "postgresql://", 1)

    violations: list[tuple[str, float]] = []

    try:
        conn = psycopg2.connect(dsn)
    except psycopg2.OperationalError as exc:
        print("Query budget check FAILED:")
        print(f"  Could not connect to DATABASE_URL_SYNC: {exc}")
        return 1

    try:
        conn.set_session(readonly=True, autocommit=True)
        with conn.cursor() as cur:
            for name, sql, params in QUERIES:
                explain_sql = f"EXPLAIN (ANALYZE, FORMAT JSON) {sql}"
                cur.execute(explain_sql, params)
                result = cur.fetchone()
                execution_time_ms = result[0][0]["Execution Time"]
                status = "PASS" if execution_time_ms <= BUDGET_MS else "FAIL"
                print(f"  [{status}] {name}: {execution_time_ms:.2f}ms (budget {BUDGET_MS}ms)")
                if execution_time_ms > BUDGET_MS:
                    violations.append((name, execution_time_ms))
    finally:
        conn.close()

    if violations:
        print("\nQuery budget check FAILED:")
        for name, ms in violations:
            print(f"  Over budget: {name} took {ms:.2f}ms (budget {BUDGET_MS}ms)")
        return 1

    print("\nAll dashboard queries within budget.")
    return 0


if __name__ == "__main__":
    sys.exit(run_query_budgets())
