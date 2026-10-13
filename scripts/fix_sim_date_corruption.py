"""Remediation for corrupted dim_tempo.ano values in fato_obitos (SIM date bug).

`sim_staging.py`'s DTOBITO byte-order detection used to decide YYYYMMDD vs.
DDMMYYYY per batch by sniffing a single row. Real DDMMYYYY batches whose
first non-null DTOBITO happened to have day-of-death == 20 were misclassified
as YYYYMMDD -- DD+MM concatenates to "20MM" (e.g. day=31, month=12 -> "2012"),
which falls inside the sniff's "looks like a year" window and misclassifies
the ENTIRE batch. Every other row's `ano` was then computed from its DD+MM
digits instead of its real year (e.g. a genuine 31 Dec 2022 death,
"31122022", produced ano=3112 instead of 2022). The staging fix (whole-batch
format scoring, immune to any single outlier row) prevents new corruption;
this script repairs already-loaded fato_obitos rows.

For every cached data/raw/SIM_{uf}_{ano}.parquet file, re-stages it through
the FIXED stage_sim() to recompute correct (ano, mes) per row, then matches
back to fato_obitos by numero_do -- the same identity key
scripts/backfill_raca_cor.py uses, and safe here because numero_do (for real
pysus data) is built from the caller-supplied file-level `ano` argument plus
CODUF/CONTADOR, never from the buggy DTOBITO-derived `ano`, so it is
unaffected by the corruption and stable across re-staging.

For each fato_obitos row whose CURRENT dim_tempo_id points at a corrupted
(ano > 2025) dim_tempo entry, this script re-points it at the correct
dim_tempo row (created if it does not yet exist) via
    UPDATE fato_obitos SET dim_tempo_id = %s WHERE numero_do = %s
No other column is ever touched, and corrupted dim_tempo rows themselves are
never deleted (they may still be referenced elsewhere; removing them is out
of scope for this repair).

Idempotent: a fato_obitos row already pointing at a valid dim_tempo entry no
longer matches the "dim_tempo_id points at ano > 2025" selection on a second
run, so it is left untouched; re-running after a full fix is a no-op.

Guarded like scripts/backfill_raca_cor.py: refuses to run without an
explicit --confirm or --dry-run flag. Stdlib + pandas + psycopg2 only.
"""
import argparse
import logging
import math
import os
import re
import sys
from pathlib import Path
from typing import Optional

import pandas as pd
import psycopg2
import psycopg2.extras

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

from etl.staging.sim_staging import stage_sim  # noqa: E402 -- import after sys.path setup

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger(__name__)

_FILENAME_PATTERN = re.compile(r"^SIM_(?P<uf>[A-Z]{2})_(?P<ano>\d{4})\.parquet$")

_CORRUPTED_ANO_THRESHOLD = 2025

# Never string-interpolate values into this statement -- values travel only
# as execute_batch parameters.
_UPDATE_SQL = "UPDATE fato_obitos SET dim_tempo_id = %s WHERE numero_do = %s"

_BATCH_SIZE = 1000


def _iter_sim_files(raw_dir: Path, ufs: list[str] | None, anos: list[int] | None):
    """Yield (path, uf, ano) for every SIM_*.parquet file matching the scoping filters.

    Mirrors scripts/backfill_raca_cor.py's helper of the same name --
    duplicated rather than imported to keep this script self-contained, per
    the project's existing standalone-script convention (scripts/ has no
    shared package layer).
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


def find_corrupted_tempo_ids(conn) -> dict[int, int]:
    """Return {dim_tempo.id: dim_tempo.ano} for every corrupted (ano > threshold) row."""
    cur = conn.cursor()
    cur.execute(
        "SELECT id, ano FROM dim_tempo WHERE ano > %s",
        (_CORRUPTED_ANO_THRESHOLD,),
    )
    rows = cur.fetchall()
    cur.close()
    return {row[0]: row[1] for row in rows}


def find_affected_numero_dos(conn, corrupted_ids: list[int]) -> tuple[set[str], int]:
    """Return (distinct numero_do set, total row count) currently pointing at a corrupted dim_tempo row.

    Distinct numero_do is what drives the UPDATE (WHERE numero_do = %s
    updates every revision row sharing that numero_do, matching
    backfill_raca_cor.py's established pattern -- the death date does not
    change across SIM revisions of the same certificate). The total row
    count is reported separately since one numero_do can cover >1 row.
    """
    if not corrupted_ids:
        return set(), 0

    cur = conn.cursor()
    cur.execute(
        "SELECT COUNT(*) FROM fato_obitos WHERE dim_tempo_id = ANY(%s)",
        (corrupted_ids,),
    )
    total_rows = cur.fetchone()[0]

    cur.execute(
        "SELECT DISTINCT numero_do FROM fato_obitos WHERE dim_tempo_id = ANY(%s)",
        (corrupted_ids,),
    )
    numero_dos = {row[0] for row in cur.fetchall()}
    cur.close()
    return numero_dos, total_rows


def _load_tempo_cache(conn) -> dict[tuple[int, Optional[int]], int]:
    """Preload dim_tempo into an (ano, mes) -> id cache, mirroring DimCache.tempo."""
    cur = conn.cursor()
    cur.execute("SELECT id, ano, mes FROM dim_tempo")
    cache = {(row[1], row[2]): row[0] for row in cur.fetchall()}
    cur.close()
    return cache


def _get_or_create_tempo_id(
    conn, tempo_cache: dict, ano: int, mes: Optional[int], dry_run: bool
) -> int:
    """Return the correct dim_tempo.id for (ano, mes), creating it if needed.

    Mirrors etl.mart.dim_lookup.DimCache.get_or_create_tempo_id. In dry_run
    mode, a not-yet-existing (ano, mes) is assigned a negative placeholder id
    (never a real INSERT) so counts and per-file previews can still report
    against a stable key without touching the database.
    """
    ano = int(ano)
    mes = int(mes) if mes is not None else None
    key = (ano, mes)
    if key in tempo_cache:
        return tempo_cache[key]

    if dry_run:
        placeholder_id = -(len(tempo_cache) + 1)
        tempo_cache[key] = placeholder_id
        return placeholder_id

    trimestre = math.ceil(mes / 3) if mes else None
    semestre = math.ceil(mes / 6) if mes else None

    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO dim_tempo (ano, mes, trimestre, semestre)
        VALUES (%s, %s, %s, %s)
        RETURNING id
        """,
        (ano, mes, trimestre, semestre),
    )
    new_id = cur.fetchone()[0]
    cur.close()

    tempo_cache[key] = new_id
    logger.info("dim_tempo created during remediation: ano=%s mes=%s id=%s", ano, mes, new_id)
    return new_id


def fix_sim_date_corruption(
    conn,
    raw_dir: Path,
    dry_run: bool = False,
    ufs: list[str] | None = None,
    anos: list[int] | None = None,
) -> dict:
    """Repair fato_obitos.dim_tempo_id for rows corrupted by the DTOBITO sniff bug.

    dry_run=True performs the full scan, re-staging, and matching, but issues
    zero UPDATE/INSERT statements and zero commits -- the returned counts
    describe what WOULD happen.
    """
    corrupted = find_corrupted_tempo_ids(conn)
    if not corrupted:
        logger.info("No corrupted dim_tempo rows found (ano > %d) -- nothing to do", _CORRUPTED_ANO_THRESHOLD)
        return {
            "corrupted_tempo_rows": 0,
            "corrupted_fato_obitos_rows": 0,
            "affected_numero_dos": 0,
            "files_scanned": 0,
            "files_skipped_unparseable": 0,
            "rows_updated": 0,
            "numero_dos_fixed": 0,
            "numero_dos_not_matched": 0,
            "unmatched_numero_dos": [],
        }

    affected, total_corrupted_rows = find_affected_numero_dos(conn, list(corrupted.keys()))
    logger.info(
        "Found %d corrupted dim_tempo row(s) (ano > %d), affecting %d fato_obitos row(s) across %d distinct numero_do",
        len(corrupted),
        _CORRUPTED_ANO_THRESHOLD,
        total_corrupted_rows,
        len(affected),
    )

    tempo_cache = _load_tempo_cache(conn)
    matched, files_skipped_unparseable = _iter_sim_files(raw_dir, ufs, anos)

    remaining = set(affected)
    files_scanned = 0
    rows_fixed = 0
    numero_dos_fixed = 0
    batch: list[tuple] = []

    cur = conn.cursor() if not dry_run else None

    try:
        for path, uf, ano in matched:
            if not remaining:
                break

            files_scanned += 1
            df = pd.read_parquet(path)
            staged = stage_sim(df, uf=uf, ano=ano)
            staged = staged[["numero_do", "ano", "mes"]]

            file_fixed = 0
            for row in staged.itertuples(index=False):
                if row.numero_do not in remaining:
                    continue

                new_tempo_id = _get_or_create_tempo_id(
                    conn, tempo_cache, row.ano, row.mes, dry_run
                )
                remaining.discard(row.numero_do)
                numero_dos_fixed += 1
                file_fixed += 1

                if dry_run:
                    continue

                batch.append((new_tempo_id, row.numero_do))
                if len(batch) >= _BATCH_SIZE:
                    psycopg2.extras.execute_batch(cur, _UPDATE_SQL, batch, page_size=1000)
                    conn.commit()
                    rows_fixed += len(batch)
                    batch = []

            if file_fixed:
                logger.info(
                    "%s %s: re-staged %d rows, matched %d corrupted numero_do",
                    uf, ano, len(staged), file_fixed,
                )

        if not dry_run and batch:
            psycopg2.extras.execute_batch(cur, _UPDATE_SQL, batch, page_size=1000)
            conn.commit()
            rows_fixed += len(batch)
            batch = []
    finally:
        if cur is not None:
            cur.close()

    if remaining:
        logger.warning(
            "%d numero_do could not be matched against any cached SIM_*.parquet file "
            "(source file missing, renamed, or outside the scanned --uf/--ano scope)",
            len(remaining),
        )

    return {
        "corrupted_tempo_rows": len(corrupted),
        "corrupted_fato_obitos_rows": total_corrupted_rows,
        "affected_numero_dos": len(affected),
        "files_scanned": files_scanned,
        "files_skipped_unparseable": files_skipped_unparseable,
        # rows_updated is always actual DB writes (0 in dry-run mode);
        # numero_dos_fixed is the matched/would-fix count in either mode.
        "rows_updated": rows_fixed,
        "numero_dos_fixed": numero_dos_fixed,
        "numero_dos_not_matched": len(remaining),
        "unmatched_numero_dos": sorted(remaining),
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
            "Repair fato_obitos.dim_tempo_id rows corrupted by the SIM DTOBITO "
            "byte-order sniff bug (dim_tempo.ano > 2025)."
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
        help="Comma-separated UF codes to scope the scan to (default: all cached files).",
    )
    parser.add_argument(
        "--ano",
        default=None,
        help="Comma-separated reference years to scope the scan to (default: all cached files).",
    )
    parser.add_argument(
        "--confirm",
        action="store_true",
        default=False,
        help="Required to actually issue UPDATE/INSERT statements against the database.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        default=False,
        help="Report what would be fixed without issuing any UPDATE/INSERT.",
    )
    args = parser.parse_args()

    print(
        "=" * 70 + "\n"
        "SIM DATE CORRUPTION REPAIR -- this will UPDATE fato_obitos.dim_tempo_id\n"
        "for rows currently linked to a corrupted (ano > 2025) dim_tempo entry,\n"
        "re-deriving the correct year from cached data/raw/SIM_*.parquet via the\n"
        "fixed stage_sim(). No other column is touched, and corrupted dim_tempo\n"
        "rows are never deleted.\n" + "=" * 70
    )

    if not args.confirm and not args.dry_run:
        print(
            "\nRefusing to run: no action was taken. Re-run with --confirm to "
            "perform the repair, or --dry-run to preview it."
        )
        return 1

    database_url_sync = os.environ.get("DATABASE_URL_SYNC", "")
    if not database_url_sync:
        raise RuntimeError("DATABASE_URL_SYNC environment variable is required")

    conn = psycopg2.connect(database_url_sync)
    try:
        ufs = _parse_scope(args.uf)
        anos = _parse_ano_scope(args.ano)
        result = fix_sim_date_corruption(
            conn, Path(args.raw_dir), dry_run=args.dry_run, ufs=ufs, anos=anos
        )
    finally:
        conn.close()

    label = "Would fix" if args.dry_run else "Fixed"
    print(
        f"\n{label}:\n"
        f"  corrupted dim_tempo rows (ano > {_CORRUPTED_ANO_THRESHOLD}) : {result['corrupted_tempo_rows']}\n"
        f"  corrupted fato_obitos rows          : {result['corrupted_fato_obitos_rows']}\n"
        f"  affected numero_do (distinct)       : {result['affected_numero_dos']}\n"
        f"  files scanned                       : {result['files_scanned']}\n"
        f"  files skipped (unparseable)         : {result['files_skipped_unparseable']}\n"
        f"  numero_do matched                   : {result['numero_dos_fixed']}\n"
        f"  fato_obitos rows updated            : {result['rows_updated']}\n"
        f"  numero_do NOT matched                : {result['numero_dos_not_matched']}\n"
    )
    if result["unmatched_numero_dos"]:
        print("Unmatched numero_do (first 20):")
        for nd in result["unmatched_numero_dos"][:20]:
            print(f"  {nd}")

    return 0 if result["numero_dos_not_matched"] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
