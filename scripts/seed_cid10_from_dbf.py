"""Seed dim_causa from CID10.DBF downloaded from DataSUS FTP.

Downloads CID10.DBF from:
  ftp://ftp.datasus.gov.br/dissemin/publicos/SIM/CID10/TABELAS/CID10.DBF

Saves locally to backend/seeds/data/CID10.DBF (skips download if file exists).
Upserts all 14k+ CID-10 codes into dim_causa.

Usage (from repo root):
    DATABASE_URL_SYNC=postgresql://... python scripts/seed_cid10_from_dbf.py
"""
import ftplib
import logging
import os
import sys
from pathlib import Path

import psycopg2

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))
from seeds.cid10_loader import _get_chapter, _assert_chapters

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger(__name__)

FTP_HOST = "ftp.datasus.gov.br"
FTP_PATH = "/dissemin/publicos/SIM/CID10/TABELAS/CID10.DBF"
LOCAL_DBF = Path(__file__).resolve().parent.parent / "backend" / "seeds" / "data" / "CID10.DBF"

DATABASE_URL = os.environ["DATABASE_URL_SYNC"]


def download_dbf() -> None:
    if LOCAL_DBF.exists():
        logger.info("CID10.DBF already exists (%d bytes) — skipping download", LOCAL_DBF.stat().st_size)
        return
    LOCAL_DBF.parent.mkdir(parents=True, exist_ok=True)
    logger.info("Downloading %s from %s", FTP_PATH, FTP_HOST)
    ftp = ftplib.FTP(FTP_HOST, timeout=60)
    ftp.login()
    with open(LOCAL_DBF, "wb") as f:
        ftp.retrbinary(f"RETR {FTP_PATH}", f.write)
    ftp.quit()
    logger.info("Downloaded: %d bytes", LOCAL_DBF.stat().st_size)


def parse_dbf() -> list[dict]:
    try:
        from dbfread import DBF
    except ImportError:
        logger.error("dbfread not installed — run: pip install dbfread")
        sys.exit(1)

    db = DBF(str(LOCAL_DBF), encoding="latin-1")
    rows = []
    for rec in db:
        code = str(rec.get("CID10", "")).strip().upper()
        descr = str(rec.get("DESCR", "")).strip()
        if not code or not descr:
            continue
        # DESCR format: "A00   Colera" — strip the code prefix
        # Use everything after the first space block
        parts = descr.split(None, 1)
        descricao = parts[1] if len(parts) > 1 else descr
        # Normalize 4-char codes: "A000" → use as-is; 3-char "A00" → use as-is
        categoria = code[:3]
        subcategoria = code if len(code) > 3 else None
        capitulo = _get_chapter(categoria)
        rows.append({
            "codigo_cid10": code,
            "descricao": descricao[:500],
            "capitulo": capitulo,
            "categoria": categoria,
            "subcategoria": subcategoria,
            "grupo_descricao": None,
        })
    logger.info("Parsed %d CID-10 codes from DBF", len(rows))
    return rows


def upsert(conn, rows: list[dict]) -> int:
    batch_size = 500
    total = 0
    for i in range(0, len(rows), batch_size):
        batch = rows[i: i + batch_size]
        with conn.cursor() as cur:
            psycopg2.extras.execute_values(
                cur,
                """
                INSERT INTO dim_causa
                    (codigo_cid10, descricao, capitulo, categoria, subcategoria, grupo_descricao)
                VALUES %s
                ON CONFLICT (codigo_cid10) DO UPDATE SET
                    descricao = EXCLUDED.descricao,
                    capitulo  = EXCLUDED.capitulo,
                    categoria = EXCLUDED.categoria,
                    subcategoria = EXCLUDED.subcategoria
                """,
                [(r["codigo_cid10"], r["descricao"], r["capitulo"],
                  r["categoria"], r["subcategoria"], r["grupo_descricao"]) for r in batch],
            )
        conn.commit()
        total += len(batch)
        if total % 2000 == 0 or total == len(rows):
            logger.info("Upserted %d / %d", total, len(rows))
    return total


def main() -> None:
    download_dbf()
    rows = parse_dbf()

    import psycopg2.extras  # noqa: F401 — used inside upsert
    conn = psycopg2.connect(DATABASE_URL)
    try:
        n = upsert(conn, rows)
        logger.info("dim_causa seeded: %d rows", n)
        _assert_chapters(conn)
    finally:
        conn.close()


if __name__ == "__main__":
    main()
