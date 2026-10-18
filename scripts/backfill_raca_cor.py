"""Standalone raca_cor backfill for already-loaded fato_obitos rows.

`run_pipeline`'s `_already_loaded(conn, hash_md5)` hash dedup causes SIM files
unchanged since their last load to be skipped entirely -- re-running `make
full` alone can never reach the ~373 already-cached 2010-2023 UF-year rows to
add `raca_cor` to them. This script bypasses `audit_ingestao` entirely: it
reads the cached `data/raw/SIM_{uf}_{ano}.parquet` files directly, derives
`numero_do` through the exact same `stage_sim` code path the original load
used, and issues targeted batched
    UPDATE fato_obitos SET raca_cor = %s WHERE numero_do = %s
statements. No other column is ever written and no other table is touched.

`WHERE numero_do = %s` intentionally updates ALL revision rows sharing that
`numero_do` -- the real uniqueness key is `(numero_do, revisao_numero)`, but
`raca_cor` is a demographic attribute that is invariant across revisions of
the same DO, so updating every matching row is correct.

Guarded like scripts/reset_sih_data.py: refuses to run without an explicit
--confirm, --dry-run, or --verify flag. Stdlib + pandas + psycopg2 only.
"""
import argparse
import logging
import os
import re
import sys
from pathlib import Path

import pandas as pd
import psycopg2
import psycopg2.extras

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

from etl.staging.sim_staging import stage_sim  # noqa: E402 -- import after sys.path setup

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger(__name__)

_FILENAME_PATTERN = re.compile(r"^SIM_(?P<uf>[A-Z]{2})_(?P<ano>\d{4})\.parquet$")

# Never string-interpolate values into this statement -- values travel only
# as execute_batch parameters.
_UPDATE_SQL = "UPDATE fato_obitos SET raca_cor = %s WHERE numero_do = %s"

_BATCH_SIZE = 1000


def _iter_sim_files(raw_dir: Path, ufs: list[str] | None, anos: list[int] | None):
    """Yield (path, uf, ano) for every SIM_*.parquet file matching the scoping filters.

    Shared between backfill_raca_cor and verify_raca_cor so the two code
    paths cannot drift -- the SIM_*.parquet glob is
    defined exactly once, here.
    """
    files_skipped_unparseable = 0
    matched = []

    for path in sorted(raw_dir.glob("SIM_*.parquet")):
        match = _FILENAME_PATTERN.match(path.name)
        if not match:
            files_skipped_unparseable += 1
            continue

        uf = match.group("uf")
        ano = int(match.group("ano"))

        if ufs is not None and uf not in ufs:
            continue
        if anos is not None and ano not in anos:
            continue

        matched.append((path, uf, ano))

    return matched, files_skipped_unparseable


def backfill_raca_cor(
    conn,
    raw_dir: Path,
    dry_run: bool = False,
    ufs: list[str] | None = None,
    anos: list[int] | None = None,
) -> dict:
    """Backfill raca_cor on already-loaded fato_obitos rows from cached SIM Parquet.

    For each cached data/raw/SIM_{uf}_{ano}.parquet file, stages the raw
    DataFrame through stage_sim(df, uf=uf, ano=ano) -- reusing stage_sim is
    mandatory, it is the only place the "DO" + ano + coduf + CONTADOR
    surrogate key is constructed, and it applies the same row-drop validation
    as the original load (invalid DTOBITO, empty CAUSABAS, null CODMUNRES),
    so this backfill naturally targets exactly the rows that were loaded.

    Rows whose staged raca_cor is None are skipped (not sent as an UPDATE) --
    they are already NULL in the DB, so sending them would be a pointless
    write across ~15M rows. They are counted under source_blank so
    verify_raca_cor can compare against the DB NULL count.

    dry_run=True performs the full scan and key derivation but issues zero
    UPDATE statements and zero commits.
    """
    matched, files_skipped_unparseable = _iter_sim_files(raw_dir, ufs, anos)

    files_scanned = 0
    rows_read = 0
    rows_updated = 0
    source_blank = 0
    per_file = []

    cur = conn.cursor() if not dry_run else None
    batch: list[tuple] = []

    try:
        for path, uf, ano in matched:
            files_scanned += 1
            df = pd.read_parquet(path)
            staged = stage_sim(df, uf=uf, ano=ano)
            staged = staged[["numero_do", "raca_cor"]]

            file_rows = len(staged)
            file_blank = int(staged["raca_cor"].isna().sum())

            rows_read += file_rows
            source_blank += file_blank
            per_file.append({"uf": uf, "ano": ano, "rows": file_rows, "blank": file_blank})

            logger.info(
                "backfill %s %s: %d rows, %d blank", uf, ano, file_rows, file_blank
            )

            if dry_run:
                continue

            for row in staged.itertuples(index=False):
                if row.raca_cor is None:
                    continue
                batch.append((row.raca_cor, row.numero_do))
                if len(batch) >= _BATCH_SIZE:
                    psycopg2.extras.execute_batch(cur, _UPDATE_SQL, batch, page_size=1000)
                    conn.commit()
                    rows_updated += len(batch)
                    batch = []

        if not dry_run and batch:
            psycopg2.extras.execute_batch(cur, _UPDATE_SQL, batch, page_size=1000)
            conn.commit()
            rows_updated += len(batch)
            batch = []
    finally:
        if cur is not None:
            cur.close()

    return {
        "files_scanned": files_scanned,
        "files_skipped_unparseable": files_skipped_unparseable,
        "rows_read": rows_read,
        "rows_updated": rows_updated,
        "source_blank": source_blank,
        "per_file": per_file,
    }


def verify_raca_cor(conn, raw_dir: Path, tolerance_pct: float = 1.0) -> dict:
    """Compare the raw-source raca_cor blank rate against the DB NULL rate.

    Re-runs the same Parquet scan as backfill_raca_cor (via the shared
    _iter_sim_files helper, so the two code paths cannot drift) to compute
    source-side totals, then queries the database for the DB-side totals.

    A small delta_pct is expected -- the DB contains only rows that survived
    stage_sim validation and dimension-FK resolution, so an exact match is
    not required. A LARGE delta means the backfill lost data and must be
    investigated; a small one is normal drift, hence the tolerance_pct band.
    Only SELECT statements are issued here -- no DML.
    """
    matched, files_skipped_unparseable = _iter_sim_files(raw_dir, None, None)

    source_rows = 0
    source_blank = 0

    for path, uf, ano in matched:
        df = pd.read_parquet(path)
        staged = stage_sim(df, uf=uf, ano=ano)
        source_rows += len(staged)
        source_blank += int(staged["raca_cor"].isna().sum())

    source_blank_pct = (100.0 * source_blank / source_rows) if source_rows else 0.0

    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM fato_obitos")
    db_rows = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM fato_obitos WHERE raca_cor IS NULL")
    db_null = cur.fetchone()[0]
    cur.execute(
        "SELECT raca_cor, COUNT(*) FROM fato_obitos GROUP BY raca_cor ORDER BY raca_cor"
    )
    distribution = cur.fetchall()
    cur.close()

    db_null_pct = (100.0 * db_null / db_rows) if db_rows else 0.0
    delta_pct = abs(db_null_pct - source_blank_pct)
    passed = delta_pct <= tolerance_pct

    return {
        "files_skipped_unparseable": files_skipped_unparseable,
        "source_rows": source_rows,
        "source_blank": source_blank,
        "source_blank_pct": source_blank_pct,
        "db_rows": db_rows,
        "db_null": db_null,
        "db_null_pct": db_null_pct,
        "db_rows_with_raca_cor": db_rows - db_null,
        "delta_pct": delta_pct,
        "tolerance_pct": tolerance_pct,
        "passed": passed,
        "distribution": distribution,
    }


def _parse_scope(value: str | None) -> list[str] | None:
    if not value:
        return None
    return [v.strip() for v in value.split(",") if v.strip()]


def _parse_ano_scope(value: str | None) -> list[int] | None:
    if not value:
        return None
    return [int(v.strip()) for v in value.split(",") if v.strip()]


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Backfill raca_cor on already-loaded fato_obitos rows "
            "-- bypasses audit_ingestao hash dedup."
        )
    )
    parser.add_argument(
        "--raw-dir",
        default="data/raw",
        help="Directory containing cached SIM_*.parquet files (default: data/raw).",
    )
    parser.add_argument(
        "--uf",
        default=None,
        help="Comma-separated UF codes to scope the backfill to (default: all cached files).",
    )
    parser.add_argument(
        "--ano",
        default=None,
        help="Comma-separated reference years to scope the backfill to (default: all cached files).",
    )
    parser.add_argument(
        "--confirm",
        action="store_true",
        default=False,
        help="Required to actually issue UPDATE statements against the database.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        default=False,
        help="Report what would be updated without issuing any UPDATE.",
    )
    parser.add_argument(
        "--verify",
        action="store_true",
        default=False,
        help="Compare the raw-source raca_cor blank rate against the DB NULL rate and exit non-zero on divergence.",
    )
    parser.add_argument(
        "--tolerance",
        type=float,
        default=1.0,
        help="Allowed absolute percentage-point delta for --verify (default: 1.0).",
    )
    args = parser.parse_args()

    print(
        "=" * 70 + "\n"
        "RACA_COR BACKFILL -- this will UPDATE fato_obitos.raca_cor for rows\n"
        "matched by numero_do, derived from cached data/raw/SIM_*.parquet\n"
        "files via the same stage_sim() key derivation as the original load.\n"
        "No other column or table is ever written. audit_ingestao is never\n"
        "read or written by this script.\n" + "=" * 70
    )

    if not args.confirm and not args.dry_run and not args.verify:
        print(
            "\nRefusing to run: no action was taken. Re-run with --confirm to "
            "perform the backfill, --dry-run to preview it, or --verify to "
            "check coverage."
        )
        return 1

    database_url_sync = os.environ.get("DATABASE_URL_SYNC", "")
    if not database_url_sync:
        raise RuntimeError("DATABASE_URL_SYNC environment variable is required")

    conn = psycopg2.connect(database_url_sync)
    try:
        if args.verify:
            result = verify_raca_cor(
                conn, Path(args.raw_dir), tolerance_pct=args.tolerance
            )
            status = "PASS" if result["passed"] else "FAIL"
            print(
                f"\nRACA_COR VERIFY: {status}\n"
                f"  source_rows       : {result['source_rows']}\n"
                f"  source_blank      : {result['source_blank']}\n"
                f"  source_blank_pct  : {result['source_blank_pct']:.2f}%\n"
                f"  db_rows           : {result['db_rows']}\n"
                f"  db_null           : {result['db_null']}\n"
                f"  db_null_pct       : {result['db_null_pct']:.2f}%\n"
                f"  db_rows_with_raca_cor : {result['db_rows_with_raca_cor']}\n"
                f"  delta_pct         : {result['delta_pct']:.2f}%\n"
                f"  tolerance_pct     : {result['tolerance_pct']:.2f}%\n"
            )
            print("Per-code distribution:")
            for code, count in result["distribution"]:
                label = code if code is not None else "NULL"
                print(f"  {label}: {count}")

            return 0 if result["passed"] else 1

        ufs = _parse_scope(args.uf)
        anos = _parse_ano_scope(args.ano)
        result = backfill_raca_cor(
            conn, Path(args.raw_dir), dry_run=args.dry_run, ufs=ufs, anos=anos
        )
    finally:
        conn.close()

    label = "Would update" if args.dry_run else "Updated"
    print(
        f"\n{label}:\n"
        f"  files scanned              : {result['files_scanned']}\n"
        f"  files skipped (unparseable): {result['files_skipped_unparseable']}\n"
        f"  rows read                  : {result['rows_read']}\n"
        f"  rows updated                : {result['rows_updated']}\n"
        f"  source blank (skipped)     : {result['source_blank']}\n"
    )

    return 0


if __name__ == "__main__":
    sys.exit(main())
