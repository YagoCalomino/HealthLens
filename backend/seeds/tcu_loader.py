"""TCU population seed loader.

Loads municipal population estimates from tcu_populacao.csv into dim_populacao.

# Source: TCU Resolucao 35/2023 and prior years. Full table at: https://www.tcu.gov.br/
# The committed CSV is SYNTHETIC — replace with official TCU data before production use.
"""

import logging
import os
from pathlib import Path

import pandas as pd
import psycopg2

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger(__name__)

CSV_PATH = Path(__file__).parent / "data" / "tcu_populacao.csv"


def _load_csv() -> pd.DataFrame:
    df = pd.read_csv(CSV_PATH, comment="#", dtype={"codigo_ibge_6": str})
    logger.info(f"Read {len(df)} rows from {CSV_PATH}")

    null_counts = df.isnull().sum()
    if null_counts.any():
        raise ValueError(
            f"Null values found in tcu_populacao.csv: {null_counts[null_counts > 0].to_dict()}"
        )

    invalid_codes = df[df["codigo_ibge_6"].str.len() != 6]
    if not invalid_codes.empty:
        raise ValueError(
            f"{len(invalid_codes)} rows have codigo_ibge_6 with length != 6"
        )

    return df


def _upsert_batch(conn, df: pd.DataFrame) -> int:
    cur = conn.cursor()
    rows = df[["codigo_ibge_6", "ano", "populacao_total"]].values.tolist()
    batch_size = 1000
    loaded = 0
    for i in range(0, len(rows), batch_size):
        batch = rows[i : i + batch_size]
        cur.executemany(
            """
            INSERT INTO dim_populacao (codigo_ibge_6, ano, populacao_total, fonte)
            VALUES (%s, %s, %s, 'TCU')
            ON CONFLICT (codigo_ibge_6, ano) DO UPDATE SET
                populacao_total = EXCLUDED.populacao_total
            """,
            batch,
        )
        loaded += len(batch)
        conn.commit()
        logger.info(f"Upserted {loaded}/{len(rows)} dim_populacao rows")
    cur.close()
    return loaded


def _assert_post_load(conn, df: pd.DataFrame) -> None:
    cur = conn.cursor()
    cur.execute("SELECT COUNT(DISTINCT ano) FROM dim_populacao")
    n_anos = cur.fetchone()[0]
    if n_anos < 5:
        raise AssertionError(
            f"Post-load assertion failed: expected >= 5 distinct years, got {n_anos}"
        )
    cur.close()
    n_municipios = df["codigo_ibge_6"].nunique()
    logger.info(
        f"TCU population loaded: {len(df)} rows, {n_anos} years, {n_municipios} municipalities"
    )


def load_tcu() -> None:
    database_url = os.environ.get("DATABASE_URL_SYNC", "")
    if not database_url:
        raise RuntimeError("DATABASE_URL_SYNC environment variable is required")

    df = _load_csv()

    conn = psycopg2.connect(database_url)
    try:
        total = _upsert_batch(conn, df)
        logger.info(f"TCU load complete: {total} rows loaded")
        _assert_post_load(conn, df)
    finally:
        conn.close()


if __name__ == "__main__":
    load_tcu()
