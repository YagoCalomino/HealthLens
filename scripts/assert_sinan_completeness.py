"""Assert SINAN completeness across the (agravo, ano) grid.

Operator-run script: run this after the (operator-executed) full SINAN
re-ingestion completes, against the real PostgreSQL database, to prove (or
disprove) that fato_notificacoes has non-zero, plausible row counts for
every (agravo, ano) combination in the grid, that every agravo's loaded
data spans all 27 UFs, and that no year shows
an unexplained row-count cliff -- with documented, non-masking exceptions
via scripts/sinan_agravo_allowlist.yaml.

The grid is (agravo, ano), NEVER (agravo, UF): pysus.sinan() has no
state= parameter (live-verified by the pysus SINAN spike --
docs/pysus-270-sinan-spike-findings.md, check 2/3), so every download is
already one NATIONAL file spanning all 27 UFs. A UF is therefore not a
re-fetchable checkpoint unit -- UF completeness can only be measured as
distinct-sigla_uf coverage within already-loaded data (check 3 below), not
as a grid dimension analogous to (agravo, ano).

Stdlib + psycopg2 + pyyaml only. Follows the CLI convention established by
scripts/validate_env.py (def main() -> int, sys.exit(main()), PASS/FAIL
printed output), the DATABASE_URL_SYNC guard style from
backend/etl/pipeline.py, and the allowlist-aware grid-check shape of
scripts/assert_sih_completeness.py.

All human-facing output uses "notificações" -- each row in fato_notificacoes
is one notification, never an asserted confirmed diagnosis.
"""
import argparse
import os
import sys

import psycopg2
import yaml

ALL_AGRAVOS = ["DENG", "CHIK", "ANIM"]
# Default lower bound is 2015 because chikungunya's national SINAN series
# begins mid-decade, while dengue and animais peçonhentos have deeper
# history reachable by overriding --ano (and the matching SINAN_ANOS
# Makefile variable). An operator widening the range must re-check the
# allowlist -- a wider range may surface additional genuinely-absent or
# preliminary years not yet documented in scripts/sinan_agravo_allowlist.yaml.
ALL_YEARS = list(range(2015, 2025))  # 2015-2024
ALL_UF_COUNT = 27


def load_allowlist(path: str) -> dict[str, set[tuple[str, int]]]:
    """Load known_absent and known_partial (AGRAVO, ano) pairs from YAML.

    A missing file is treated as an empty allowlist (both keys empty sets),
    not a crash -- the allowlist is optional documentation of known catalog
    gaps, not a required artifact for the check itself to run.
    """
    empty: dict[str, set[tuple[str, int]]] = {
        "known_absent": set(),
        "known_partial": set(),
    }
    if not os.path.exists(path):
        return empty

    with open(path) as fh:
        data = yaml.safe_load(fh) or {}

    result = dict(empty)
    for key in ("known_absent", "known_partial"):
        entries = data.get(key) or []
        result[key] = {(str(agravo).upper(), int(ano)) for agravo, ano in entries}
    return result


def assert_sinan_completeness(
    conn,
    allowlist: dict[str, set[tuple[str, int]]],
    agravos: list[str] = ALL_AGRAVOS,
    anos: list[int] = ALL_YEARS,
    min_rows: int = 1,
    min_ufs: int = ALL_UF_COUNT,
    cliff_ratio: float = 0.10,
) -> dict:
    """Run the three-check SINAN completeness gate.

    Check 1 (presence): every (agravo, ano) in the grid not listed in
    known_absent must have at least min_rows notificações.

    Check 2 (cliff): for each agravo, the count of a non-allowlisted year
    must not fall below cliff_ratio * median(that agravo's other checked
    years' counts), unless the (agravo, ano) combo is in known_partial.
    Skipped for an agravo with fewer than three checked years, since a
    median over one or two points is not meaningful.

    Check 3 (UF coverage): every agravo with
    any loaded rows must show at least min_ufs distinct sigla_uf values.
    An agravo with zero rows is already reported by check 1 and is not
    double-reported here.

    Raises a single AssertionError summarizing all failures across the
    three checks. On success returns a dict with keys checked, present,
    allowlisted_absent, allowlisted_partial, uf_coverage, total_rows and
    lowest (the ten lowest-count combos, for eyeball plausibility).
    """
    known_absent = allowlist.get("known_absent", set())
    known_partial = allowlist.get("known_partial", set())

    cur = conn.cursor()

    # Query A -- per-(agravo, ano) counts.
    cur.execute(
        """
        SELECT da.codigo, dt.ano, COUNT(*) AS n
        FROM fato_notificacoes fn
        JOIN dim_agravo da ON fn.dim_agravo_id = da.id
        JOIN dim_tempo dt ON fn.dim_tempo_id = dt.id
        GROUP BY da.codigo, dt.ano
        """
    )
    count_rows = cur.fetchall()

    # Query B -- per-agravo UF coverage.
    cur.execute(
        """
        SELECT da.codigo, COUNT(DISTINCT dl.sigla_uf) AS n_ufs
        FROM fato_notificacoes fn
        JOIN dim_agravo da ON fn.dim_agravo_id = da.id
        JOIN dim_local dl ON fn.dim_local_id = dl.id
        GROUP BY da.codigo
        """
    )
    uf_rows = cur.fetchall()
    cur.close()

    present = {(agravo, ano): n for agravo, ano, n in count_rows}
    uf_coverage = {agravo: n_ufs for agravo, n_ufs in uf_rows}

    failures: list[str] = []

    # Check 1 -- presence.
    presence_failures = []
    for agravo in agravos:
        for ano in anos:
            if (agravo, ano) in known_absent:
                continue
            n = present.get((agravo, ano), 0)
            if n < min_rows:
                presence_failures.append((agravo, ano, n))
    if presence_failures:
        combos_str = ", ".join(f"{a}/{y} (n={n})" for a, y, n in presence_failures)
        failures.append(
            f"presence: {len(presence_failures)} of {len(agravos) * len(anos)} "
            f"agravo-year combos missing or below min-rows={min_rows}: {combos_str}"
        )

    # Check 2 -- row-count cliff, per agravo.
    cliff_failures = []
    for agravo in agravos:
        checked_years = [
            (ano, present.get((agravo, ano), 0))
            for ano in anos
            if (agravo, ano) not in known_absent
        ]
        if len(checked_years) < 3:
            continue
        counts = sorted(n for _, n in checked_years)
        mid = len(counts) // 2
        if len(counts) % 2:
            median = counts[mid]
        else:
            median = (counts[mid - 1] + counts[mid]) / 2
        threshold = cliff_ratio * median
        for ano, n in checked_years:
            if (agravo, ano) in known_partial:
                continue
            if n < threshold:
                cliff_failures.append((agravo, ano, n, median))
    if cliff_failures:
        combos_str = ", ".join(
            f"{a}/{y} (n={n}, median={med:.0f}, "
            f"see scripts/sinan_agravo_allowlist.yaml known_partial)"
            for a, y, n, med in cliff_failures
        )
        failures.append(
            f"cliff: {len(cliff_failures)} agravo-year combos below "
            f"cliff_ratio={cliff_ratio} of their agravo's median: {combos_str}"
        )

    # Check 3 -- UF coverage.
    uf_failures = []
    for agravo in agravos:
        total_for_agravo = sum(
            present.get((agravo, ano), 0) for ano in anos
        )
        if total_for_agravo == 0:
            # Already reported by check 1 -- do not double-report.
            continue
        n_ufs = uf_coverage.get(agravo, 0)
        if n_ufs < min_ufs:
            uf_failures.append((agravo, n_ufs))
    if uf_failures:
        combos_str = ", ".join(f"{a} (n_ufs={n})" for a, n in uf_failures)
        failures.append(
            f"uf-coverage: {len(uf_failures)} agravos below min-ufs={min_ufs} "
            f"distinct sigla_uf values: {combos_str}"
        )

    if failures:
        raise AssertionError("SINAN completeness FAILED:\n  " + "\n  ".join(failures))

    checked_present = {
        (agravo, ano): present.get((agravo, ano), 0)
        for agravo in agravos
        for ano in anos
        if (agravo, ano) not in known_absent
    }
    total_rows = sum(checked_present.values())
    lowest = sorted(checked_present.items(), key=lambda kv: kv[1])[:10]

    return {
        "checked": len(agravos) * len(anos),
        "present": checked_present,
        "allowlisted_absent": sorted(known_absent),
        "allowlisted_partial": sorted(known_partial),
        "uf_coverage": {a: uf_coverage.get(a, 0) for a in agravos},
        "total_rows": total_rows,
        "lowest": lowest,
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Assert SINAN completeness across the (agravo, ano) grid, "
        "including per-agravo 27-UF coverage."
    )
    parser.add_argument(
        "--allowlist",
        default="scripts/sinan_agravo_allowlist.yaml",
        help="Path to the known_absent/known_partial (agravo, ano) allowlist YAML "
        "(default: scripts/sinan_agravo_allowlist.yaml).",
    )
    parser.add_argument(
        "--min-rows",
        type=int,
        default=1,
        help="Minimum row count for an agravo-year combo to count as present (default: 1).",
    )
    parser.add_argument(
        "--agravo",
        default=",".join(ALL_AGRAVOS),
        help="Comma-separated agravo codes to check (default: all three).",
    )
    parser.add_argument(
        "--ano",
        default=",".join(str(y) for y in ALL_YEARS),
        help="Comma-separated reference years to check (default: 2015-2024).",
    )
    parser.add_argument(
        "--min-ufs",
        type=int,
        default=ALL_UF_COUNT,
        help="Minimum distinct sigla_uf coverage required per agravo (default: 27).",
    )
    parser.add_argument(
        "--cliff-ratio",
        type=float,
        default=0.10,
        help="A non-allowlisted year failing below cliff_ratio * median of its "
        "agravo's other checked years fails the check (default: 0.10).",
    )
    args = parser.parse_args()

    agravos = [a.strip().upper() for a in args.agravo.split(",") if a.strip()]
    anos = [int(y.strip()) for y in args.ano.split(",") if y.strip()]

    database_url_sync = os.environ.get("DATABASE_URL_SYNC", "")
    if not database_url_sync:
        raise RuntimeError("DATABASE_URL_SYNC environment variable is required")

    allowlist = load_allowlist(args.allowlist)

    conn = psycopg2.connect(database_url_sync)
    try:
        try:
            result = assert_sinan_completeness(
                conn,
                allowlist,
                agravos=agravos,
                anos=anos,
                min_rows=args.min_rows,
                min_ufs=args.min_ufs,
                cliff_ratio=args.cliff_ratio,
            )
        except AssertionError as exc:
            print(str(exc))
            print(
                "\nRemediation: re-run the failing units with "
                "`make ingest-sinan SINAN_AGRAVOS=<agravo> SINAN_ANOS=<ano>`, then "
                "re-run `make spike-pysus-sinan` to confirm what the catalog "
                "actually holds for that unit. There is no catalog-scan script for "
                "SINAN (pysus's list_files() helper crashed the interpreter when "
                "called repeatedly in a loop on Windows during "
                "research), so the spike script's real data fetch is the "
                "reliable evidence path instead. Only after confirming the real "
                "catalog state, add a dated entry to the appropriate key "
                "(known_absent or known_partial) in "
                "scripts/sinan_agravo_allowlist.yaml."
            )
            return 1
    finally:
        conn.close()

    print(
        f"SINAN completeness OK: {result['checked']} combos checked, "
        f"{len(result['allowlisted_absent'])} allowlisted absences, "
        f"{len(result['allowlisted_partial'])} allowlisted partials, "
        f"{result['total_rows']} total notificações, 0 unexplained gaps."
    )
    print("\nPer-agravo UF coverage:")
    for agravo, n_ufs in sorted(result["uf_coverage"].items()):
        print(f"  {agravo}: {n_ufs} distinct UFs")
    print("\nLowest-count combos (plausibility check):")
    for (agravo, ano), n in result["lowest"]:
        print(f"  {agravo}/{ano}: {n} notificações")

    return 0


if __name__ == "__main__":
    sys.exit(main())
