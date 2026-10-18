"""Assert full SIM coverage across the 27 UF x 2010-2024 grid.

Operator-run script: run this after the (operator-executed) full `make full`
SIM 2024 re-ingestion completes, against the real PostgreSQL database, to
prove (or disprove) two things:

  1. fato_obitos has non-zero, plausible row counts for every UF-year
     combination (with documented, non-masking exceptions via
     scripts/sim_year_allowlist.yaml) -- with a per-UF 2024 breakout, since
     2024 is the newly ingested year.
  2. no numero_do maps to more than one fato_obitos row, proving the
     (numero_do, revisao_numero) upsert key held through re-ingestion.

Mirrors scripts/assert_sih_completeness.py structurally.
Stdlib + psycopg2 + pyyaml only. Follows the CLI convention established by
scripts/validate_env.py (def main() -> int, sys.exit(main()), PASS/FAIL
printed output) and the DATABASE_URL_SYNC guard style from
backend/etl/pipeline.py.
"""
import argparse
import os
import sys

import psycopg2
import yaml

# Same 27 UF codes as scripts/assert_sih_completeness.py / scan_sim_catalog.py.
ALL_UFS = [
    "AC", "AL", "AM", "AP", "BA", "CE", "DF", "ES", "GO", "MA", "MG", "MS",
    "MT", "PA", "PB", "PE", "PI", "PR", "RJ", "RN", "RO", "RR", "RS", "SC",
    "SE", "SP", "TO",
]
ALL_YEARS = list(range(2010, 2025))


def load_allowlist(path: str) -> set[tuple[str, int]]:
    """Load known_absent (UF, ano) pairs from a YAML allowlist file.

    A missing file is treated as an empty allowlist, not a crash -- the
    allowlist is optional documentation of known catalog gaps, not a
    required artifact for the check itself to run.
    """
    if not os.path.exists(path):
        return set()

    with open(path) as fh:
        data = yaml.safe_load(fh) or {}

    entries = data.get("known_absent") or []
    return {(str(uf).upper(), int(ano)) for uf, ano in entries}


def assert_sim_completeness(
    conn,
    allowlist: set[tuple[str, int]],
    ufs: list[str] = ALL_UFS,
    anos: list[int] = ALL_YEARS,
    min_rows: int = 1,
) -> dict:
    """Assert every (uf, ano) combo has at least `min_rows` fato_obitos rows.

    A combo fails when it is absent from the query result OR its count is
    below `min_rows`, UNLESS it is in `allowlist`. An allowlist entry for one
    combo never suppresses the failure of a *different* missing combo --
    each combo is checked independently against the allowlist set.
    """
    cur = conn.cursor()
    cur.execute(
        """
        SELECT dl.sigla_uf, dt.ano, COUNT(*) AS n
        FROM fato_obitos fo
        JOIN dim_local dl ON fo.dim_local_id = dl.id
        JOIN dim_tempo dt ON fo.dim_tempo_id = dt.id
        GROUP BY dl.sigla_uf, dt.ano
        """
    )
    rows = cur.fetchall()
    cur.close()

    present = {(uf, ano): n for uf, ano, n in rows}

    failing = []
    for uf in ufs:
        for ano in anos:
            if (uf, ano) in allowlist:
                continue
            n = present.get((uf, ano), 0)
            if n < min_rows:
                failing.append((uf, ano, n))

    if failing:
        combos_str = ", ".join(f"{uf}/{ano} (n={n})" for uf, ano, n in failing)
        raise AssertionError(
            f"SIM completeness FAILED: {len(failing)} of {len(ufs) * len(anos)} "
            f"UF-year combos missing or below min-rows={min_rows}: {combos_str}"
        )

    checked_present = {
        (uf, ano): present.get((uf, ano), 0)
        for uf in ufs
        for ano in anos
        if (uf, ano) not in allowlist
    }
    total_rows = sum(checked_present.values())
    lowest = sorted(checked_present.items(), key=lambda kv: kv[1])[:10]

    coverage_2024 = {uf: present.get((uf, 2024), 0) for uf in ufs}

    return {
        "checked": len(ufs) * len(anos),
        "present": checked_present,
        "allowlisted": sorted(allowlist),
        "total_rows": total_rows,
        "lowest": lowest,
        "coverage_2024": coverage_2024,
    }


def assert_no_duplicate_numerodo(conn) -> int:
    """Return the count of numero_do values with more than one fato_obitos row.

    Ports the query from backend/etl/mart/obitos_loader.py::assert_no_duplicate_numerodo,
    which is deliberately kept disabled inline in load_obitos for multi-million-row
    performance reasons -- this script runs it once, out of band. Unlike the
    obitos_loader version, this returns the count rather than raising, so
    main() owns the exit-code decision and can report both gates in one run.
    """
    cur = conn.cursor()
    cur.execute(
        """
        SELECT COUNT(*) FROM (
            SELECT numero_do FROM fato_obitos
            GROUP BY numero_do HAVING COUNT(*) > 1
        ) dups
        """
    )
    count = cur.fetchone()[0]
    cur.close()
    return count


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Assert SIM completeness across the 27 UF x 2010-2024 grid, "
        "plus zero duplicate numero_do."
    )
    parser.add_argument(
        "--allowlist",
        default="scripts/sim_year_allowlist.yaml",
        help="Path to the known-absent UF-year allowlist YAML (default: scripts/sim_year_allowlist.yaml).",
    )
    parser.add_argument(
        "--min-rows",
        type=int,
        default=1,
        help="Minimum row count for a UF-year combo to count as present (default: 1).",
    )
    parser.add_argument(
        "--uf",
        default=",".join(ALL_UFS),
        help="Comma-separated UF codes to check (default: all 27).",
    )
    parser.add_argument(
        "--ano",
        default=",".join(str(y) for y in ALL_YEARS),
        help="Comma-separated reference years to check (default: 2010-2024).",
    )
    parser.add_argument(
        "--skip-duplicates",
        action="store_true",
        default=False,
        help="Skip the full-table duplicate numero_do GROUP BY (expensive on a "
        "very large table). Skipping this forfeits the second check "
        "(proof the (numero_do, revisao_numero) upsert key held).",
    )
    args = parser.parse_args()

    ufs = [u.strip().upper() for u in args.uf.split(",") if u.strip()]
    anos = [int(y.strip()) for y in args.ano.split(",") if y.strip()]

    database_url_sync = os.environ.get("DATABASE_URL_SYNC", "")
    if not database_url_sync:
        raise RuntimeError("DATABASE_URL_SYNC environment variable is required")

    allowlist = load_allowlist(args.allowlist)

    conn = psycopg2.connect(database_url_sync)
    try:
        coverage_ok = True
        result = None
        try:
            result = assert_sim_completeness(
                conn, allowlist, ufs=ufs, anos=anos, min_rows=args.min_rows
            )
        except AssertionError as exc:
            coverage_ok = False
            print(str(exc))
            print(
                "\nRemediation: run scripts/scan_sim_catalog.py for the failing "
                "combos; if the catalog genuinely has no SIM files, add them to "
                "the allowlist with a dated comment."
            )

        duplicate_count = None
        if not args.skip_duplicates:
            duplicate_count = assert_no_duplicate_numerodo(conn)
    finally:
        conn.close()

    if result is not None:
        print(
            f"SIM completeness OK: {result['checked']} combos checked, "
            f"{len(result['allowlisted'])} allowlisted absences, "
            f"{result['total_rows']} total rows, 0 unexplained gaps."
        )
        print("\nLowest-count combos (plausibility check):")
        for (uf, ano), n in result["lowest"]:
            print(f"  {uf}/{ano}: {n} rows")
        print("\n2024 coverage by UF:")
        for uf in ufs:
            if uf in result["coverage_2024"]:
                print(f"  {uf}: {result['coverage_2024'][uf]} rows")

    if duplicate_count is None:
        print(
            "\nDuplicate numero_do check: SKIPPED (--skip-duplicates set -- "
            "forfeits the second check)."
        )
    elif duplicate_count == 0:
        print("\nDuplicate numero_do check: OK -- 0 numero_do values with duplicate rows.")
    else:
        coverage_ok = False
        print(
            f"\nDuplicate numero_do check: FAILED -- {duplicate_count} numero_do "
            "values map to more than one fato_obitos row."
        )
        print(
            "\nRemediation: a non-zero count means the (numero_do, revisao_numero) "
            "upsert key did not hold. The likely cause is a numero_do derivation "
            "change in stage_sim producing new surrogate keys for rows that "
            "already existed under old keys -- investigate the derivation, "
            "never delete rows."
        )

    return 0 if coverage_ok else 1


if __name__ == "__main__":
    sys.exit(main())
