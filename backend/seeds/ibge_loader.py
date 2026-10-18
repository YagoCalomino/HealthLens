"""IBGE municipalities seed loader.

Fetches all Brazilian municipalities from the IBGE localities API and loads
them into dim_local with both 6-digit and 7-digit IBGE codes.

Post-seed assertion: zero NULL codigo_ibge_7 (critical per architecture decisions).
"""

import gzip
import json
import logging
import os
import urllib.error
import urllib.request
from datetime import date
from pathlib import Path

import psycopg2

from seeds.utils.ibge_check_digit import compute_check_digit

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger(__name__)

IBGE_API_URL = "https://servicodados.ibge.gov.br/api/v1/localidades/municipios"
# Snapshot of the API response (id, nome, UF only) for when the API is down or
# answers with an empty body, which happens intermittently.
FALLBACK_PATH = Path(__file__).resolve().parent / "data" / "municipios_fallback.json"

REGIAO_MAP = {
    "AC": "Norte",
    "AM": "Norte",
    "AP": "Norte",
    "PA": "Norte",
    "RO": "Norte",
    "RR": "Norte",
    "TO": "Norte",
    "AL": "Nordeste",
    "BA": "Nordeste",
    "CE": "Nordeste",
    "MA": "Nordeste",
    "PB": "Nordeste",
    "PE": "Nordeste",
    "PI": "Nordeste",
    "RN": "Nordeste",
    "SE": "Nordeste",
    "DF": "Centro-Oeste",
    "GO": "Centro-Oeste",
    "MS": "Centro-Oeste",
    "MT": "Centro-Oeste",
    "ES": "Sudeste",
    "MG": "Sudeste",
    "RJ": "Sudeste",
    "SP": "Sudeste",
    "PR": "Sul",
    "RS": "Sul",
    "SC": "Sul",
}

VALID_FROM = date(2023, 1, 1)


def _load_fallback() -> list[dict]:
    logger.warning(
        f"Using local municipality fallback {FALLBACK_PATH.name}."
        " Re-run when the IBGE API is back to pick up any boundary changes."
    )
    with FALLBACK_PATH.open(encoding="utf-8") as f:
        data: list[dict] = json.load(f)
    logger.info(f"Loaded {len(data)} municipalities from fallback")
    return data


def _fetch_municipios() -> list[dict]:
    logger.info(f"Fetching municipalities from {IBGE_API_URL}")
    try:
        with urllib.request.urlopen(IBGE_API_URL, timeout=60) as resp:
            raw = resp.read()
            # IBGE API returns Content-Encoding: gzip even without an explicit Accept-Encoding header
            if resp.info().get("Content-Encoding", "") == "gzip" and raw:
                raw = gzip.decompress(raw)
    except (urllib.error.URLError, OSError, EOFError) as exc:
        logger.warning(f"IBGE API request failed: {exc}. Using local fallback.")
        return _load_fallback()

    if not raw:
        logger.warning("IBGE API returned an empty response. Using local fallback.")
        return _load_fallback()

    try:
        data = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        logger.warning(
            f"IBGE API returned a non-JSON response ({exc}); first bytes: {raw[:120]!r}."
            " Using local fallback."
        )
        return _load_fallback()
    logger.info(f"Fetched {len(data)} municipalities")
    return data


def _get_uf_obj(item: dict) -> dict:
    # microrregiao may be null (not just absent) for DF / newly restructured municipalities.
    # item.get("microrregiao", {}) returns None when the key exists with a null value,
    # so `or {}` is required to guard the chained .get() calls.
    micro = item.get("microrregiao") or {}
    uf = (micro.get("mesorregiao") or {}).get("UF") or {}
    if uf:
        return uf
    # Fallback: newer IBGE regional division (regiao-imediata / regiao-intermediaria)
    # used by municipalities that don't have a microrregiao in the v1 API response.
    imediata = item.get("regiao-imediata") or {}
    return (imediata.get("regiao-intermediaria") or {}).get("UF") or {}


def _parse_municipios(data: list[dict]) -> list[dict]:
    rows: list[dict] = []
    mismatches = 0
    for item in data:
        ibge_7 = str(item["id"])
        nome = item["nome"]
        uf_obj = _get_uf_obj(item)
        sigla_uf = uf_obj.get("sigla", "")
        nome_uf = uf_obj.get("nome", "")
        codigo_uf = str(uf_obj.get("id", ""))[:2]
        regiao = REGIAO_MAP.get(sigla_uf, "Desconhecida")

        # Derive 6-digit code by stripping the check digit from the IBGE-provided 7-digit id.
        codigo_6 = ibge_7[:6]

        # Verify check digit against our algorithm. Seven municipalities have IBGE-documented
        # exceptions where the official code doesn't match the Luhn/EAN variant — log a warning
        # but always store the IBGE-authoritative 7-digit code (ibge_7), never the recomputed one.
        expected_check = compute_check_digit(codigo_6)
        actual_check = ibge_7[6] if len(ibge_7) == 7 else ""
        if expected_check != actual_check:
            logger.warning(
                "Check digit mismatch for %s (%s): computed=%s, actual=%s"
                " — storing IBGE-official code as-is",
                nome,
                ibge_7,
                expected_check,
                actual_check,
            )
            mismatches += 1

        rows.append(
            {
                "codigo_ibge_6": codigo_6,
                "codigo_ibge_7": ibge_7,  # IBGE API is authoritative; do NOT recompute
                "nome_municipio": nome[:100],
                "nome_uf": nome_uf[:50],
                "sigla_uf": sigla_uf[:2],
                "codigo_uf": codigo_uf[:2],
                "regiao": regiao,
                "valid_from": VALID_FROM,
                "is_current": True,
                "ativo": True,
                "codigo_sucessor": None,
            }
        )

    if mismatches:
        logger.warning(
            "%d check digit mismatch(es) found — these are IBGE-documented exceptions."
            " Official 7-digit codes stored as-is; TopoJSON matching is unaffected.",
            mismatches,
        )
    else:
        logger.info("All check digits verified: 0 mismatches")

    return rows


def _upsert_batch(conn, rows: list[dict]) -> int:
    cur = conn.cursor()
    loaded = 0
    batch_size = 500
    for i in range(0, len(rows), batch_size):
        batch = rows[i : i + batch_size]
        cur.executemany(
            """
            INSERT INTO dim_local (
                codigo_ibge_6, codigo_ibge_7, nome_municipio, nome_uf,
                sigla_uf, codigo_uf, regiao, valid_from,
                is_current, ativo, codigo_sucessor
            ) VALUES (
                %(codigo_ibge_6)s, %(codigo_ibge_7)s, %(nome_municipio)s, %(nome_uf)s,
                %(sigla_uf)s, %(codigo_uf)s, %(regiao)s, %(valid_from)s,
                %(is_current)s, %(ativo)s, %(codigo_sucessor)s
            )
            ON CONFLICT (codigo_ibge_6, valid_from) DO UPDATE SET
                codigo_ibge_7 = EXCLUDED.codigo_ibge_7,
                nome_municipio = EXCLUDED.nome_municipio,
                nome_uf = EXCLUDED.nome_uf,
                sigla_uf = EXCLUDED.sigla_uf,
                codigo_uf = EXCLUDED.codigo_uf,
                regiao = EXCLUDED.regiao,
                is_current = EXCLUDED.is_current,
                ativo = EXCLUDED.ativo
            """,
            batch,
        )
        loaded += len(batch)
        conn.commit()
        logger.info(f"Upserted {loaded}/{len(rows)} dim_local rows")
    cur.close()
    return loaded


def _assert_post_seed(conn) -> None:
    cur = conn.cursor()

    # Critical assertion: zero NULL codigo_ibge_7
    cur.execute("SELECT COUNT(*) FROM dim_local WHERE codigo_ibge_7 IS NULL")
    null_count = cur.fetchone()[0]
    if null_count != 0:
        raise AssertionError(
            f"dim_local assertion failed: {null_count} rows with NULL codigo_ibge_7"
        )
    logger.info("Assertion passed: 0 rows with NULL codigo_ibge_7")

    # Total count assertion
    cur.execute("SELECT COUNT(*) FROM dim_local")
    total = cur.fetchone()[0]
    if total < 5570:
        raise AssertionError(
            f"dim_local assertion failed: expected >= 5570 rows, got {total}"
        )
    logger.info(f"Assertion passed: {total} municipalities loaded (>= 5570)")

    # Correctness assertion: SP capital (355030) must map to 3550308
    cur.execute(
        "SELECT codigo_ibge_7 FROM dim_local WHERE codigo_ibge_6 = '355030' LIMIT 1"
    )
    row = cur.fetchone()
    actual = row[0] if row else "row not found"
    if not row or actual != "3550308":
        raise AssertionError(
            f"dim_local assertion failed: SP capital codigo_ibge_7 expected '3550308', got '{actual}'"
        )
    logger.info("Assertion passed: SP capital 7-digit code is correct (3550308)")

    cur.close()


def load_ibge() -> None:
    database_url = os.environ.get("DATABASE_URL_SYNC", "")
    if not database_url:
        raise RuntimeError("DATABASE_URL_SYNC environment variable is required")

    raw = _fetch_municipios()
    rows = _parse_municipios(raw)

    conn = psycopg2.connect(database_url)
    try:
        total = _upsert_batch(conn, rows)
        logger.info(f"IBGE load complete: {total} rows loaded")
        _assert_post_seed(conn)
    finally:
        conn.close()


if __name__ == "__main__":
    load_ibge()
