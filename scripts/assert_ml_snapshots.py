"""Assert ML snapshot completeness for the two-year clustering re-run and the
forecast retrain.

Operator-run script: run this after (operator-executed) `make cluster-snapshots`
and `make retrain-forecasts` complete against the real PostgreSQL database, to
prove -- or disprove -- that `municipio_cluster_assignments` holds two
freshly-computed `ano_referencia` snapshots at least 3 years apart, that
`forecast_resultados` is anchored to `ano_referencia = 2024` with the
2025-2027 horizon present (not a partial retrain leaving a mixed
2023/2024 label) -- extra past forecast years are expected for municípios
with short historical series and do not fail the check -- and
that `mv_taxa_municipio_ano` was refreshed with 2024 SIM data before
`/risco-prospectivo` relies on it.

Stdlib + psycopg2 only. Follows the CLI convention established by
scripts/assert_sinan_completeness.py and scripts/validate_env.py
(def main() -> int, sys.exit(main()), PASS/FAIL printed output), and the
DATABASE_URL_SYNC guard style from backend/etl/pipeline.py.

The decision logic is separated from DB access (run_checks issues only
SELECT statements) so it is unit-testable without a live database -- see
backend/tests/test_scripts_assert_ml_snapshots.py.

All human-facing output uses the project's Portuguese domain vocabulary
(município, ano_referencia), consistent with the sibling assert scripts.
"""
import argparse
import os
import sys

import psycopg2

_ESPERADO_REF = 2024
_ESPERADO_HORIZONTE = (2025, 2026, 2027)
_ESPERADO_MV_ANO = 2024
_MIN_GAP_ANOS = 3


def check_cluster_snapshots(anos, min_gap: int = _MIN_GAP_ANOS) -> tuple[bool, str]:
    """Pass only when at least two distinct ano_referencia values exist AND
    the widest gap between them is >= min_gap years. A pre-existing
    extra snapshot (e.g. a lingering 2023 row) does not break this check --
    it only requires that *some* pair of distinct years is far enough apart.
    """
    distinct = sorted(set(anos))
    if len(distinct) < 2:
        return (
            False,
            f"cluster snapshots: apenas {len(distinct)} ano_referencia distinto(s) "
            f"encontrado(s) ({distinct}) -- são necessários pelo menos 2 anos, "
            f"com pelo menos {min_gap} anos de diferença.",
        )
    gap = max(distinct) - min(distinct)
    if gap < min_gap:
        return (
            False,
            f"cluster snapshots: anos encontrados {distinct}, maior intervalo "
            f"{gap} < {min_gap} anos exigidos.",
        )
    return (
        True,
        f"cluster snapshots: anos encontrados {distinct}, maior intervalo {gap} "
        f"anos (>= {min_gap} exigido).",
    )


def check_forecast_currency(
    ano_referencia_values,
    ano_forecast_values,
    esperado_ref: int = _ESPERADO_REF,
    esperado_horizonte: tuple = _ESPERADO_HORIZONTE,
) -> tuple[bool, str]:
    """Pass only when the distinct ano_referencia set is exactly {esperado_ref}
    (a lingering 2023 alongside 2024 means a partial retrain -- fail) and the
    distinct ano_forecast set contains the full expected future horizon.

    ano_forecast is checked as a superset, not an exact match: municípios with
    short historical series (e.g. RJ sample municípios with SIM data starting
    only in 2023) get forecasts anchored to their own last available year, so
    ano_forecast can legitimately include years before esperado_horizonte
    (e.g. 2023 or 2024) alongside it. That is correct per-município behavior,
    not a partial retrain -- the retrain-completeness signal lives in
    ano_referencia (checked above), not in the presence of extra past
    forecast years.
    """
    ref_set = set(ano_referencia_values)
    horizonte_set = set(ano_forecast_values)
    esperado_ref_set = {esperado_ref}
    esperado_horizonte_set = set(esperado_horizonte)

    failures = []
    if ref_set != esperado_ref_set:
        failures.append(
            f"ano_referencia encontrado {sorted(ref_set)}, esperado "
            f"{sorted(esperado_ref_set)} (retrain parcial detectado se houver "
            "mais de um valor)."
        )
    if not esperado_horizonte_set.issubset(horizonte_set):
        faltando = sorted(esperado_horizonte_set - horizonte_set)
        failures.append(
            f"ano_forecast encontrado {sorted(horizonte_set)}, faltando anos "
            f"do horizonte esperado: {faltando}."
        )
    if failures:
        return (False, "forecast currency: " + " ".join(failures))
    return (
        True,
        f"forecast currency: ano_referencia={sorted(ref_set)}, "
        f"ano_forecast={sorted(horizonte_set)} (horizonte esperado "
        f"{sorted(esperado_horizonte_set)} presente) -- conforme esperado.",
    )


def check_mv_freshness(max_ano, esperado: int = _ESPERADO_MV_ANO) -> tuple[bool, str]:
    """Pass only when max_ano == esperado. Failure message carries the
    literal remediation command.
    """
    if max_ano != esperado:
        return (
            False,
            f"mv_taxa_municipio_ano desatualizada: MAX(ano) para fonte='SIM' "
            f"é {max_ano}, esperado {esperado}. Remediação: execute "
            "REFRESH MATERIALIZED VIEW CONCURRENTLY mv_taxa_municipio_ano;",
        )
    return (True, f"mv_taxa_municipio_ano atualizada: MAX(ano)={max_ano}.")


def run_checks(conn) -> dict:
    """Issue the real DB queries and feed the pure check functions above.

    Raises AssertionError summarizing all failures. On success returns a
    dict with keys cluster_anos, cluster_counts, forecast_ano_referencia,
    forecast_ano_forecast, mv_max_ano, all populated from the queries.
    """
    cur = conn.cursor()

    cur.execute(
        """
        SELECT DISTINCT ano_referencia FROM municipio_cluster_assignments
        WHERE algoritmo = 'KMeans' AND n_clusters = 6
        ORDER BY ano_referencia
        """
    )
    cluster_anos = [row[0] for row in cur.fetchall()]

    cur.execute(
        """
        SELECT ano_referencia, COUNT(*) FROM municipio_cluster_assignments
        WHERE algoritmo = 'KMeans' AND n_clusters = 6
        GROUP BY ano_referencia
        ORDER BY ano_referencia
        """
    )
    cluster_counts = cur.fetchall()

    cur.execute("SELECT DISTINCT ano_referencia FROM forecast_resultados")
    forecast_ano_referencia = [row[0] for row in cur.fetchall()]

    cur.execute("SELECT DISTINCT ano_forecast FROM forecast_resultados")
    forecast_ano_forecast = [row[0] for row in cur.fetchall()]

    cur.execute(
        "SELECT MAX(ano) FROM mv_taxa_municipio_ano WHERE fonte = 'SIM'"
    )
    mv_max_ano = cur.fetchone()[0]

    cur.close()

    failures: list[str] = []
    messages: list[str] = []

    zero_row_snapshots = [ano for ano, n in cluster_counts if n == 0]
    if zero_row_snapshots:
        failures.append(
            f"cluster snapshots com zero linhas: {zero_row_snapshots} -- "
            "cada snapshot esperado deve ter contagem não-nula."
        )

    ok, msg = check_cluster_snapshots(cluster_anos)
    messages.append(msg)
    if not ok:
        failures.append(msg)

    ok, msg = check_forecast_currency(forecast_ano_referencia, forecast_ano_forecast)
    messages.append(msg)
    if not ok:
        failures.append(msg)

    ok, msg = check_mv_freshness(mv_max_ano)
    messages.append(msg)
    if not ok:
        failures.append(msg)

    if failures:
        raise AssertionError(
            "ML snapshots FAILED:\n  " + "\n  ".join(failures)
        )

    return {
        "cluster_anos": cluster_anos,
        "cluster_counts": cluster_counts,
        "forecast_ano_referencia": forecast_ano_referencia,
        "forecast_ano_forecast": forecast_ano_forecast,
        "mv_max_ano": mv_max_ano,
        "messages": messages,
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Assert ML retraining completeness: two cluster snapshots "
        ">=3 years apart, forecasts anchored to 2024 with a 2025-2027 horizon, "
        "and a fresh mv_taxa_municipio_ano materialized view."
    )
    parser.add_argument(
        "--database-url",
        default=None,
        help="PostgreSQL connection string override (default: DATABASE_URL_SYNC "
        "environment variable).",
    )
    args = parser.parse_args()

    database_url_sync = args.database_url or os.environ.get("DATABASE_URL_SYNC", "")
    if not database_url_sync:
        raise RuntimeError(
            "DATABASE_URL_SYNC environment variable is required "
            "(or pass --database-url)."
        )

    conn = psycopg2.connect(database_url_sync)
    try:
        try:
            result = run_checks(conn)
        except AssertionError as exc:
            print(str(exc))
            print("\nFAIL")
            return 1
    finally:
        conn.close()

    print("Per-snapshot contagem de municípios (municipio_cluster_assignments):")
    for ano, n in result["cluster_counts"]:
        print(f"  ano_referencia={ano}: {n} municípios")
    print()
    for msg in result["messages"]:
        print(f"  OK: {msg}")
    print("\nPASS")

    return 0


if __name__ == "__main__":
    sys.exit(main())
