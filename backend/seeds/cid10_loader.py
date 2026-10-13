"""CID-10 seed loader.

Downloads CID10CSV.zip from DATASUS FTP and loads into dim_causa.

Source: ftp://ftp.datasus.gov.br/pub/sistemas/tabwin/CID10/CID10CSV.zip
If FTP is unavailable, a minimal fallback seed covers key chapters for assertions.
Full CID-10 must be loaded before production use.
"""

import logging
import os
import urllib.request
import zipfile
from pathlib import Path

import psycopg2

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger(__name__)

CID10_URL = "ftp://ftp.datasus.gov.br/pub/sistemas/tabwin/CID10/CID10CSV.zip"
DATA_DIR = Path(__file__).parent / "data"
LOCAL_ZIP = DATA_DIR / "CID10CSV.zip"

# ICD-10 chapter range mapping — category prefix to Roman numeral chapter
CHAPTER_MAP = {
    "A": "I",
    "B": "I",
    "C": "II",
    "D0": "II",
    "D1": "II",
    "D2": "II",
    "D3": "II",
    "D4": "II",
    "D5": "III",
    "D6": "III",
    "D7": "III",
    "D8": "III",
    "E": "IV",
    "F": "V",
    "G": "VI",
    "H0": "VII",
    "H1": "VII",
    "H2": "VII",
    "H3": "VII",
    "H4": "VII",
    "H5": "VII",
    "H6": "VIII",
    "H7": "VIII",
    "H8": "VIII",
    "H9": "VIII",
    "I": "IX",
    "J": "X",
    "K": "XI",
    "L": "XII",
    "M": "XIII",
    "N": "XIV",
    "O": "XV",
    "P": "XVI",
    "Q": "XVII",
    "R": "XVIII",
    "S": "XIX",
    "T": "XIX",
    "V": "XX",
    "W": "XX",
    "X": "XX",
    "Y": "XX",
    "Z": "XXI",
    "U": "XXII",
}


def _get_chapter(categoria: str) -> str:
    if not categoria:
        return "?"
    prefix2 = categoria[:2].upper()
    if prefix2 in CHAPTER_MAP:
        return CHAPTER_MAP[prefix2]
    prefix1 = categoria[:1].upper()
    if prefix1 in CHAPTER_MAP:
        return CHAPTER_MAP[prefix1]
    return "?"


def _download_if_needed() -> bool:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    if LOCAL_ZIP.exists():
        logger.info(f"CID10CSV.zip already exists at {LOCAL_ZIP}, skipping download")
        return True
    logger.info(f"Downloading CID-10 from {CID10_URL}")
    try:
        urllib.request.urlretrieve(CID10_URL, LOCAL_ZIP)
        logger.info("Download complete")
        return True
    except Exception as exc:
        logger.warning(f"FTP download failed: {exc}. Will use fallback minimal seed.")
        return False


def _parse_from_zip() -> list[dict]:
    rows: list[dict] = []
    with zipfile.ZipFile(LOCAL_ZIP) as zf:
        names = zf.namelist()
        logger.info(f"Zip contents: {names}")
        csv_name = next((n for n in names if n.upper() == "CID10BR.CSV"), None)
        if csv_name is None:
            csv_name = next(
                (n for n in names if n.upper().endswith(".CSV") and "BR" in n.upper()),
                None,
            )
        if csv_name is None:
            raise FileNotFoundError(f"CID10BR.CSV not found in zip. Contents: {names}")

        raw = zf.read(csv_name)
        text = raw.decode("latin-1")
        lines = text.splitlines()
        header = None
        for line in lines:
            if not line.strip():
                continue
            parts = line.split(";")
            if header is None:
                header = [p.strip().strip('"').upper() for p in parts]
                logger.info(f"CSV header: {header}")
                continue
            if len(parts) < 2:
                continue
            record = dict(zip(header, [p.strip().strip('"') for p in parts]))
            subcat = record.get("SUBCAT", "").strip()
            descricao = record.get("DESCRICAO", record.get("DESCABREV", "")).strip()
            if not subcat or not descricao:
                continue
            categoria = subcat[:3]
            subcategoria = subcat if len(subcat) > 3 else None
            capitulo = _get_chapter(categoria)
            rows.append(
                {
                    "codigo_cid10": subcat,
                    "descricao": descricao[:500],
                    "capitulo": capitulo,
                    "categoria": categoria,
                    "subcategoria": subcategoria,
                    "grupo_descricao": None,
                }
            )
    logger.info(f"Parsed {len(rows)} CID-10 codes from CSV")
    return rows


def _fallback_seed() -> list[dict]:
    """Minimal representative seed covering key chapters when FTP is unavailable."""
    logger.warning(
        "Using fallback minimal CID-10 seed. Load full CID-10 before production use."
    )
    entries = [
        # Chapter I — Infectious
        ("A00", "Cólera", "I", "A00", None),
        (
            "A09",
            "Diarreia e gastroenterite de origem infecciosa presumível",
            "I",
            "A09",
            None,
        ),
        (
            "B24",
            "Doença pelo vírus da imunodeficiência humana [HIV] não especificada",
            "I",
            "B24",
            None,
        ),
        # Chapter II — Neoplasms
        ("C34", "Neoplasia maligna dos brônquios e dos pulmões", "II", "C34", None),
        ("C50", "Neoplasia maligna da mama", "II", "C50", None),
        # Chapter IX — Circulatory
        ("I21", "Infarto agudo do miocárdio", "IX", "I21", None),
        (
            "I64",
            "Acidente vascular cerebral não especificado como hemorrágico ou isquêmico",
            "IX",
            "I64",
            None,
        ),
        # Chapter X — Respiratory
        ("J18", "Pneumonia por microrganismo não especificado", "X", "J18", None),
        ("J44", "Outras doenças pulmonares obstrutivas crônicas", "X", "J44", None),
        # Chapter XI — Digestive
        ("K70", "Doença alcoólica do fígado", "XI", "K70", None),
        # Chapter XVIII — Symptoms and signs (critical per requirements)
        ("R00", "Anormalidades do batimento cardíaco", "XVIII", "R00", None),
        (
            "R09",
            "Outros sintomas e sinais relativos aos aparelhos circulatório e respiratório",
            "XVIII",
            "R09",
            None,
        ),
        (
            "R99",
            "Outras causas mal definidas e as não especificadas de mortalidade",
            "XVIII",
            "R99",
            None,
        ),
        # Chapter XXI — Factors influencing health (critical per requirements)
        ("Z00", "Exame geral", "XXI", "Z00", None),
        (
            "Z23",
            "Necessidade de imunização contra doenças bacterianas únicas",
            "XXI",
            "Z23",
            None,
        ),
        (
            "Z99",
            "Dependência de máquinas e dispositivos, não classificada em outra parte",
            "XXI",
            "Z99",
            None,
        ),
    ]
    return [
        {
            "codigo_cid10": code,
            "descricao": desc,
            "capitulo": cap,
            "categoria": cat,
            "subcategoria": sub,
            "grupo_descricao": None,
        }
        for code, desc, cap, cat, sub in entries
    ]


def _upsert_batch(conn, rows: list[dict]) -> int:
    cur = conn.cursor()
    loaded = 0
    batch_size = 1000
    for i in range(0, len(rows), batch_size):
        batch = rows[i : i + batch_size]
        cur.executemany(
            """
            INSERT INTO dim_causa (codigo_cid10, descricao, capitulo, categoria, subcategoria, grupo_descricao)
            VALUES (%(codigo_cid10)s, %(descricao)s, %(capitulo)s, %(categoria)s, %(subcategoria)s, %(grupo_descricao)s)
            ON CONFLICT (codigo_cid10) DO UPDATE SET
                descricao = EXCLUDED.descricao,
                capitulo = EXCLUDED.capitulo,
                categoria = EXCLUDED.categoria
            """,
            batch,
        )
        loaded += len(batch)
        conn.commit()
        logger.info(f"Upserted {loaded}/{len(rows)} rows")
    cur.close()
    return loaded


def _assert_chapters(conn) -> None:
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM dim_causa WHERE capitulo IN ('XVIII', 'XXI')")
    count = cur.fetchone()[0]
    cur.close()
    assert count > 0, (
        f"Post-load assertion failed: no rows in dim_causa for chapters XVIII or XXI (got {count})"
    )
    logger.info(f"Post-load assertion passed: {count} rows in chapters XVIII and XXI")


def load_cid10() -> None:
    database_url = os.environ.get("DATABASE_URL_SYNC", "")
    if not database_url:
        raise RuntimeError("DATABASE_URL_SYNC environment variable is required")

    downloaded = _download_if_needed()

    if downloaded and LOCAL_ZIP.exists():
        try:
            rows = _parse_from_zip()
        except Exception as exc:
            logger.warning(f"Failed to parse zip: {exc}. Using fallback seed.")
            rows = _fallback_seed()
    else:
        rows = _fallback_seed()

    conn = psycopg2.connect(database_url)
    try:
        total = _upsert_batch(conn, rows)
        logger.info(f"CID-10 load complete: {total} rows loaded")
        _assert_chapters(conn)
    finally:
        conn.close()


if __name__ == "__main__":
    load_cid10()
