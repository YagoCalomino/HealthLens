"""Validate committed geo files against dim_local.codigo_ibge_7.

Diffs the 7-digit municipality IBGE codes found in frontend/public/topojson/uf/*.json
against dim_local to catch a wrong/mismatched code property before it becomes a silent
map gap in the choropleth (DataSUS uses 6-digit codes, TopoJSON the 7-digit form).

File-format note (see frontend/src/lib/topojson.ts for the consumption contract): the
committed files are binary-arc TopoJSON topologies (`{"type": "Topology", "objects":
{...}}`), converted from their original GeoJSON FeatureCollection form via `npx
mapshaper -o format=topojson`. This script reads
`topology.objects[<name>].geometries[].properties` (with a `geometry.id` fallback for
the municipality code) instead of GeoJSON `features[].properties`. The object name is
whatever mapshaper derived from the input filename, so it is read dynamically from
`data["objects"].keys()` rather than hardcoded. The discovered property names are
hardcoded below (not imported from the TS module — this script must run standalone in
CI/dev without a Node toolchain).

Degrades gracefully when DATABASE_URL_SYNC is unset, SAMPLE_MODE is true, or the DB is
unreachable: still emits per-file extracted-code counts and a code-format check
(7-digit numeric) so the report is never empty.
"""
import json
import logging
import os
import re
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger(__name__)

# Hardcoded property names — see frontend/src/lib/topojson.ts for discovery notes.
MUNICIPALITY_ID_FIELD = "id"           # uf/{SIGLA}.json features: 7-digit codigo_ibge_7
UF_SIGLA_FIELD = "sigla"               # br-ufs.json features
UF_CODE_FIELD = "codigo_ibg"           # br-ufs.json features: 2-digit UF IBGE code

TOPOJSON_DIR = Path(__file__).parent.parent / "frontend" / "public" / "topojson"
UF_DIR = TOPOJSON_DIR / "uf"
BR_UFS_FILE = TOPOJSON_DIR / "br-ufs.json"
REPORT_FILE = Path(__file__).parent / "topojson_validation_report.txt"

CODE7_RE = re.compile(r"^\d{7}$")
CODE2_RE = re.compile(r"^\d{2}$")


def _iter_geometries(data: dict) -> list[dict]:
    """Yields all geometries across every object in a TopoJSON Topology.

    The object name is derived by mapshaper from the input filename (not a fixed
    constant), so this reads `data["objects"].keys()` dynamically rather than
    hardcoding a name.
    """
    objects = data.get("objects", {}) or {}
    geometries: list[dict] = []
    for obj in objects.values():
        geometries.extend(obj.get("geometries", []) or [])
    return geometries


def _extract_municipality_codes(path: Path) -> list[str]:
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    codes: list[str] = []
    for geometry in _iter_geometries(data):
        props = geometry.get("properties", {}) or {}
        value = props.get(MUNICIPALITY_ID_FIELD)
        if value is None:
            value = geometry.get("id")
        if value is not None:
            codes.append(str(value))
    return codes


def _extract_uf_codes(path: Path) -> list[tuple[str, str]]:
    """Returns list of (sigla, codigo_ibg) tuples from br-ufs.json."""
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    pairs: list[tuple[str, str]] = []
    for geometry in _iter_geometries(data):
        props = geometry.get("properties", {}) or {}
        sigla = props.get(UF_SIGLA_FIELD)
        codigo = props.get(UF_CODE_FIELD)
        if sigla is not None and codigo is not None:
            pairs.append((str(sigla), str(codigo)))
    return pairs


def _fetch_dim_local_codes() -> set[str] | None:
    """Returns the set of dim_local.codigo_ibge_7 values, or None if DB unavailable."""
    if os.environ.get("SAMPLE_MODE", "").lower() in ("true", "1"):
        logger.info("SAMPLE_MODE active — skipping DB connection")
        return None

    database_url = os.environ.get("DATABASE_URL_SYNC", "")
    if not database_url:
        logger.info("DATABASE_URL_SYNC not set — skipping DB connection")
        return None

    try:
        import psycopg2
    except ImportError:
        logger.warning("psycopg2 not installed — skipping DB connection")
        return None

    try:
        conn = psycopg2.connect(database_url, connect_timeout=5)
    except Exception as exc:
        logger.warning(f"DB connection failed: {exc}")
        return None

    try:
        cur = conn.cursor()
        cur.execute("SELECT codigo_ibge_7 FROM dim_local WHERE is_current")
        rows = cur.fetchall()
        cur.close()
        return {str(r[0]) for r in rows}
    except Exception as exc:
        logger.warning(f"dim_local query failed: {exc}")
        return None
    finally:
        conn.close()


def validate() -> str:
    lines: list[str] = []
    lines.append("TopoJSON / GeoJSON validation report")
    lines.append("=" * 60)
    lines.append(
        "Discovered property names: municipality id field="
        f"'{MUNICIPALITY_ID_FIELD}', UF sigla field='{UF_SIGLA_FIELD}', "
        f"UF code field='{UF_CODE_FIELD}'"
    )
    lines.append(
        "File format: binary-arc TopoJSON topology (Topology + objects[...].geometries) — "
        "see frontend/src/lib/topojson.ts for the consumption contract."
    )
    lines.append("")

    dim_local_codes = _fetch_dim_local_codes()
    db_available = dim_local_codes is not None

    if db_available:
        lines.append(f"DB connection: OK — {len(dim_local_codes)} current dim_local rows")
    else:
        lines.append("DB connection: NOT AVAILABLE — code-format check only (no DB diff)")
    lines.append("")

    # -- br-ufs.json --
    lines.append(f"-- {BR_UFS_FILE.name} --")
    if BR_UFS_FILE.exists():
        uf_pairs = _extract_uf_codes(BR_UFS_FILE)
        bad_codes = [c for _, c in uf_pairs if not CODE2_RE.match(c)]
        lines.append(f"UF features: {len(uf_pairs)} (expected 27)")
        if bad_codes:
            lines.append(f"  WARNING: {len(bad_codes)} non-2-digit UF codes found: {bad_codes}")
        else:
            lines.append("  All UF codes are 2-digit numeric.")
    else:
        lines.append("  MISSING FILE")
    lines.append("")

    # -- per-UF municipality files --
    lines.append("-- uf/{SIGLA}.json --")
    total_codes = 0
    total_missing_in_db = 0
    for uf_file in sorted(UF_DIR.glob("*.json")):
        codes = _extract_municipality_codes(uf_file)
        total_codes += len(codes)
        non_7digit = [c for c in codes if not CODE7_RE.match(c)]
        line = f"{uf_file.stem}: {len(codes)} municipality codes extracted"
        if non_7digit:
            line += f" — WARNING: {len(non_7digit)} non-7-digit codes: {non_7digit[:5]}"
        if db_available:
            missing = [c for c in codes if c not in dim_local_codes]
            total_missing_in_db += len(missing)
            if missing:
                line += f" — {len(missing)} missing in dim_local: {missing[:5]}"
            else:
                line += " — all codes found in dim_local"
        lines.append(line)
    lines.append("")
    lines.append(f"Total municipality codes extracted: {total_codes} (expected ~5570)")
    if db_available:
        lines.append(f"Total codes missing in dim_local: {total_missing_in_db}")
        if total_missing_in_db > 0:
            lines.append(
                "  NOTE: missing codes are expected if dim_local has not been fully "
                "seeded yet (extinct/renamed municipalities aside) — re-run after "
                "`make seed` completes the IBGE load."
            )
    else:
        lines.append(
            "DB diff skipped — set DATABASE_URL_SYNC and ensure the DB is reachable "
            "to compare against dim_local.codigo_ibge_7."
        )

    return "\n".join(lines) + "\n"


def main() -> int:
    report = validate()
    REPORT_FILE.write_text(report, encoding="utf-8")
    logger.info(f"Validation report written to {REPORT_FILE}")
    print(report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
