"""One-time SIH reset -- forces a full clean re-download.

Clears all SIH state (fato_internacoes rows, SIH audit_ingestao rows, and
cached data/raw/SIH_*.parquet files) so that the existing hash-based dedup
in etl/pipeline.py (_already_loaded) and the local-Parquet-cache fallback in
etl/ingestor.py (get_or_download_sih) do NOT silently skip re-downloading or
re-loading a UF/year that looks unchanged.

Guarded: refuses to run destructively without an explicit --confirm flag.
Order-safe: deletes DB rows before cache files (see reset_sih_data()
docstring for why). SIM-preserving: never touches SIM rows/files.

Stdlib + psycopg2 only. Follows the CLI convention established by
scripts/validate_env.py and the DATABASE_URL_SYNC guard style from
backend/etl/pipeline.py.
"""
import argparse
import os
import sys
from pathlib import Path

import psycopg2


def reset_sih_data(conn, raw_dir: Path, dry_run: bool = False) -> dict:
    """Delete all SIH state: fato_internacoes rows, SIH audit rows, SIH cache files.

    Order matters: DB rows are deleted (and committed) BEFORE cache files are
    unlinked. Deleting cache files first would, on a partial failure between
    the two steps, leave a populated local Parquet cache pointing at DB rows
    that have already been cleared -- get_or_download_sih() would then find
    the stale local file and silently skip re-downloading a UF/year that in
    reality has no loaded data. Deleting DB rows first means a partial
    failure just leaves stale cache files, which is safe: get_or_download_sih
    would look for a local file, find one that IS still valid input,  or
    (once cache deletion runs to completion) simply re-download -- either
    way, idempotent and never silently incomplete.
    """
    cur = conn.cursor()

    if dry_run:
        cur.execute("SELECT COUNT(*) FROM fato_internacoes")
        fato_count = cur.fetchone()[0]
        cur.execute("SELECT COUNT(*) FROM audit_ingestao WHERE fonte = 'SIH'")
        audit_count = cur.fetchone()[0]
        cur.close()

        cache_count = len(list(raw_dir.glob("SIH_*.parquet"))) if raw_dir.exists() else 0

        return {
            "fato_rows_deleted": fato_count,
            "audit_rows_deleted": audit_count,
            "cache_files_deleted": cache_count,
        }

    # fato_internacoes has NO uf/ano columns directly (geography/time come
    # from dim_local_id/dim_tempo_id) but the table is exclusively SIH data --
    # no SIM rows to preserve -- so a full clear is correct and simplest.
    cur.execute("DELETE FROM fato_internacoes")
    fato_rows_deleted = cur.rowcount

    # audit_ingestao IS shared between SIM and SIH (fonte column) -- must
    # filter, never truncate, or SIM ingestion history would be destroyed too.
    cur.execute("DELETE FROM audit_ingestao WHERE fonte = 'SIH'")
    audit_rows_deleted = cur.rowcount

    conn.commit()
    cur.close()

    # Local Parquet cache -- delete last, after DB rows are gone and
    # committed, so a mid-failure interruption here just means
    # get_or_download_sih() re-downloads (safe, idempotent) rather than
    # silently reusing stale cache against already-cleared DB rows.
    cache_files_deleted = 0
    if raw_dir.exists():
        for f in raw_dir.glob("SIH_*.parquet"):
            f.unlink()
            cache_files_deleted += 1

    return {
        "fato_rows_deleted": fato_rows_deleted,
        "audit_rows_deleted": audit_rows_deleted,
        "cache_files_deleted": cache_files_deleted,
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="One-time reset of all SIH state -- forces a clean full re-download."
    )
    parser.add_argument(
        "--raw-dir",
        default="data/raw",
        help="Directory containing cached raw Parquet files (default: data/raw).",
    )
    parser.add_argument(
        "--confirm",
        action="store_true",
        default=False,
        help="Required to actually perform the destructive reset.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        default=False,
        help="Report what would be deleted without deleting anything.",
    )
    args = parser.parse_args()

    print(
        "=" * 70 + "\n"
        "SIH RESET -- this will DELETE:\n"
        "  * ALL rows from fato_internacoes\n"
        "  * rows from audit_ingestao WHERE fonte = 'SIH'\n"
        f"  * all SIH_*.parquet files under {args.raw_dir}\n"
        "SIM data (fato_obitos, audit_ingestao fonte='SIM', SIM_*.parquet) "
        "is never touched.\n" + "=" * 70
    )

    if not args.confirm and not args.dry_run:
        print(
            "\nRefusing to run: no destructive action was taken. "
            "Re-run with --confirm to perform the reset, or --dry-run to preview it."
        )
        return 1

    database_url_sync = os.environ.get("DATABASE_URL_SYNC", "")
    if not database_url_sync:
        raise RuntimeError("DATABASE_URL_SYNC environment variable is required")

    conn = psycopg2.connect(database_url_sync)
    try:
        result = reset_sih_data(conn, Path(args.raw_dir), dry_run=args.dry_run)
    finally:
        conn.close()

    label = "Would delete" if args.dry_run else "Deleted"
    print(
        f"\n{label}:\n"
        f"  fato_internacoes rows : {result['fato_rows_deleted']}\n"
        f"  audit_ingestao rows   : {result['audit_rows_deleted']}\n"
        f"  cache files           : {result['cache_files_deleted']}\n"
    )

    return 0


if __name__ == "__main__":
    sys.exit(main())
