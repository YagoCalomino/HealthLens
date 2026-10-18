"""Standalone dt_notific backfill for already-loaded fato_notificacoes rows.

`etl/pipeline.py::_already_loaded`'s hash dedup skips any SINAN file whose
md5 is already present in `audit_ingestao` -- re-running `make ingest-sinan`
alone can never revisit the 9,998 already-loaded ANIM/2023 rehearsal rows
to add `dt_notific` to them. This script bypasses
`audit_ingestao` entirely: it reads cached `data/raw/SINAN_{agravo}_{ano}.parquet`
files directly, runs them through `stage_sinan(df, agravo)` -- the exact
same code path the loader uses to derive `numero_notificacao` and
`dt_notific` -- and issues targeted batched
    UPDATE fato_notificacoes SET dt_notific = %s
    WHERE numero_notificacao = %s AND tipo_agravo = %s
statements. No other column is ever written and no other table is touched.

Matches on the composite natural key (numero_notificacao, tipo_agravo) --
unlike raca_cor's revision-invariant numero_do match, fato_notificacoes'
uniqueness constraint is uq_fato_notificacoes_numero_agravo, a composite.

Guarded like scripts/backfill_raca_cor.py: refuses to run without an
explicit --confirm, --dry-run, or --verify flag. Stdlib + pandas +
psycopg2 only.
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

from etl.staging.sinan_staging import stage_sinan  # noqa: E402 -- import after sys.path setup

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger(__name__)

_FILENAME_PATTERN = re.compile(r"^SINAN_(?P<agravo>[A-Z]{4})_(?P<ano>\d{4})\.parquet$")

# Never string-interpolate values into this statement -- values travel only
# as execute_batch parameters.
_UPDATE_SQL = (
    "UPDATE fato_notificacoes SET dt_notific = %s "
    "WHERE numero_notificacao = %s AND tipo_agravo = %s"
)

_BATCH_SIZE = 1000


def _iter_sinan_files(raw_dir: Path, agravos: list[str] | None, anos: list[int] | None):
    """Yield (path, agravo, ano) for every SINAN_*.parquet file matching the scoping filters.

    Shared between backfill_dt_notific and verify_dt_notific so the two code
    paths cannot drift (same anti-drift rationale as
    backfill_raca_cor._iter_sim_files).
    """
    files_skipped_unparseable = 0
    matched = []

    for path in sorted(raw_dir.glob("SINAN_*.parquet")):
        match = _FILENAME_PATTERN.match(path.name)
        if not match:
            files_skipped_unparseable += 1
            continue

        agravo = match.group("agravo")
        ano = int(match.group("ano"))

        if agravos is not None and agravo not in agravos:
            continue
        if anos is not None and ano not in anos:
            continue

        matched.append((path, agravo, ano))

    return matched, files_skipped_unparseable


def backfill_dt_notific(
    conn,
    raw_dir: Path,
    dry_run: bool = False,
    agravos: list[str] | None = None,
    anos: list[int] | None = None,
) -> dict:
    """Backfill dt_notific on already-loaded fato_notificacoes rows from cached SINAN Parquet.

    For each cached data/raw/SINAN_{agravo}_{ano}.parquet file, stages the
    raw DataFrame through stage_sinan(df, agravo) -- reusing stage_sinan is
    mandatory, it is the only place numero_notificacao and dt_notific are
    derived, and it applies the same row-drop validation as the original
    load, so this backfill naturally targets exactly the rows that were
    loaded.

    dry_run=True performs the full scan and key derivation but issues zero
    UPDATE statements and zero commits.
    """
    matched, files_skipped_unparseable = _iter_sinan_files(raw_dir, agravos, anos)

    files_scanned = 0
    rows_read = 0
    rows_updated = 0
    per_file = []

    cur = conn.cursor() if not dry_run else None
    batch: list[tuple] = []

    try:
        for path, agravo, ano in matched:
            files_scanned += 1
            df = pd.read_parquet(path)
            staged = stage_sinan(df, agravo)
            staged = staged[["numero_notificacao", "tipo_agravo", "dt_notific"]]

            file_rows = len(staged)
            rows_read += file_rows
            per_file.append({"agravo": agravo, "ano": ano, "rows": file_rows})

            logger.info("backfill %s %s: %d rows", agravo, ano, file_rows)

            if dry_run:
                continue

            for row in staged.itertuples(index=False):
                if row.dt_notific is None:
                    continue
                batch.append((row.dt_notific, row.numero_notificacao, row.tipo_agravo))
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
        "per_file": per_file,
    }


def verify_dt_notific(conn, raw_dir: Path) -> dict:
    """Verify every cached-Parquet row's (numero_notificacao, tipo_agravo) has a non-NULL dt_notific.

    Re-runs the same Parquet scan as backfill_dt_notific (via the shared
    _iter_sinan_files helper, so the two code paths cannot drift), stages
    each file, and issues one SELECT COUNT per file counting rows in
    fato_notificacoes whose key matches a staged row but whose dt_notific is
    still NULL. Only SELECT statements are issued here -- no DML.
    """
    matched, files_skipped_unparseable = _iter_sinan_files(raw_dir, None, None)

    rows_checked = 0
    shortfall = 0
    cur = conn.cursor()

    try:
        for path, agravo, ano in matched:
            df = pd.read_parquet(path)
            staged = stage_sinan(df, agravo)
            numeros = staged["numero_notificacao"].tolist()
            rows_checked += len(numeros)

            if not numeros:
                continue

            cur.execute(
                "SELECT COUNT(*) FROM fato_notificacoes "
                "WHERE tipo_agravo = %s AND numero_notificacao = ANY(%s) "
                "AND dt_notific IS NULL",
                (agravo, numeros),
            )
            shortfall += cur.fetchone()[0]
    finally:
        cur.close()

    return {
        "files_skipped_unparseable": files_skipped_unparseable,
        "rows_checked": rows_checked,
        "shortfall": shortfall,
        "passed": shortfall == 0,
    }


def _parse_scope(value: str | None) -> list[str] | None:
    if not value:
        return None
    return [v.strip().upper() for v in value.split(",") if v.strip()]


def _parse_ano_scope(value: str | None) -> list[int] | None:
    if not value:
        return None
    return [int(v.strip()) for v in value.split(",") if v.strip()]


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Backfill dt_notific on already-loaded fato_notificacoes rows "
            "-- bypasses audit_ingestao hash dedup."
        )
    )
    parser.add_argument(
        "--raw-dir",
        default="data/raw",
        help="Directory containing cached SINAN_*.parquet files (default: data/raw).",
    )
    parser.add_argument(
        "--agravo",
        default=None,
        help="Comma-separated agravo codes to scope the backfill to (default: all cached files).",
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
        help="Check that every cached-Parquet row has a non-NULL dt_notific and exit non-zero on shortfall.",
    )
    args = parser.parse_args()

    print(
        "=" * 70 + "\n"
        "DT_NOTIFIC BACKFILL -- this will UPDATE fato_notificacoes.dt_notific\n"
        "for rows matched by (numero_notificacao, tipo_agravo), derived from\n"
        "cached data/raw/SINAN_*.parquet files via the same stage_sinan()\n"
        "derivation as the original load. No other column or table is ever\n"
        "written. audit_ingestao is never read or written by this script.\n" + "=" * 70
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
            result = verify_dt_notific(conn, Path(args.raw_dir))
            status = "PASS" if result["passed"] else "FAIL"
            print(
                f"\nDT_NOTIFIC VERIFY: {status}\n"
                f"  rows_checked : {result['rows_checked']}\n"
                f"  shortfall    : {result['shortfall']}\n"
            )
            return 0 if result["passed"] else 1

        agravos = _parse_scope(args.agravo)
        anos = _parse_ano_scope(args.ano)
        result = backfill_dt_notific(
            conn, Path(args.raw_dir), dry_run=args.dry_run, agravos=agravos, anos=anos
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
    )

    return 0


if __name__ == "__main__":
    sys.exit(main())
