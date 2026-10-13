"""Assert full SIH coverage across the 27 UF x 2010-2024 grid.

Operator-run script: run this after the (operator-executed) full `make full`
SIH re-ingestion completes, against the real PostgreSQL database, to prove
(or disprove) that fato_internacoes has non-zero, plausible row counts for
every UF-year combination -- with documented, non-masking exceptions via
scripts/sih_year_allowlist.yaml.

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

# Same 27 UF codes as scripts/scan_sim_catalog.py.
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


def assert_sih_completeness(
    conn,
    allowlist: set[tuple[str, int]],
    ufs: list[str] = ALL_UFS,
    anos: list[int] = ALL_YEARS,
    min_rows: int = 1,
) -> dict:
    """Assert every (uf, ano) combo has at least `min_rows` fato_internacoes rows.

    A combo fails when it is absent from the query result OR its count is
    below `min_rows`, UNLESS it is in `allowlist`. An allowlist entry for one
    combo never suppresses the failure of a *different* missing combo --
    each combo is checked independently against the allowlist set.
    """
    cur = conn.cursor()
    cur.execute(
        """
        SELECT dl.sigla_uf, dt.ano, COUNT(*) AS n
        FROM fato_internacoes fi
        JOIN dim_local dl ON fi.dim_local_id = dl.id
        JOIN dim_tempo dt ON fi.dim_tempo_id = dt.id
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
            f"SIH completeness FAILED: {len(failing)} of {len(ufs) * len(anos)} "
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

    return {
        "checked": len(ufs) * len(anos),
        "present": checked_present,
        "allowlisted": sorted(allowlist),
        "total_rows": total_rows,
        "lowest": lowest,
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Assert SIH completeness across the 27 UF x 2010-2024 grid."
    )
    parser.add_argument(
        "--allowlist",
        default="scripts/sih_year_allowlist.yaml",
        help="Path to the known-absent UF-year allowlist YAML (default: scripts/sih_year_allowlist.yaml).",
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
    args = parser.parse_args()

    ufs = [u.strip().upper() for u in args.uf.split(",") if u.strip()]
    anos = [int(y.strip()) for y in args.ano.split(",") if y.strip()]

    database_url_sync = os.environ.get("DATABASE_URL_SYNC", "")
    if not database_url_sync:
        raise RuntimeError("DATABASE_URL_SYNC environment variable is required")

    allowlist = load_allowlist(args.allowlist)

    conn = psycopg2.connect(database_url_sync)
    try:
        try:
            result = assert_sih_completeness(
                conn, allowlist, ufs=ufs, anos=anos, min_rows=args.min_rows
            )
        except AssertionError as exc:
            print(str(exc))
            print(
                "\nRemediation: run scripts/scan_sih_catalog.py for the failing "
                "combos; if the catalog genuinely has no RD files, add them to "
                "the allowlist with a dated comment."
            )
            return 1
    finally:
        conn.close()

    print(
        f"SIH completeness OK: {result['checked']} combos checked, "
        f"{len(result['allowlisted'])} allowlisted absences, "
        f"{result['total_rows']} total rows, 0 unexplained gaps."
    )
    print("\nLowest-count combos (plausibility check):")
    for (uf, ano), n in result["lowest"]:
        print(f"  {uf}/{ano}: {n} rows")

    return 0


if __name__ == "__main__":
    sys.exit(main())
