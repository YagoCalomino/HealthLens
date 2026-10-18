"""faixa_etaria seed loader.

Upserts the 10 standard Brazilian health age groups into dim_faixa_etaria.
These groups follow the DATASUS / SVS convention used in SIM and SIH tabulations.
"""

import logging
import os

import psycopg2

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger(__name__)

# 10 standard age groups in the order required by the ETL mart loaders.
# idade_max is None for open-ended groups (75+) and the catch-all (ignorada).
FAIXAS = [
    ("0_4", "0–4 anos", 0, 4, 1),
    ("5_14", "5–14 anos", 5, 14, 2),
    ("15_24", "15–24 anos", 15, 24, 3),
    ("25_34", "25–34 anos", 25, 34, 4),
    ("35_44", "35–44 anos", 35, 44, 5),
    ("45_54", "45–54 anos", 45, 54, 6),
    ("55_64", "55–64 anos", 55, 64, 7),
    ("65_74", "65–74 anos", 65, 74, 8),
    ("75_mais", "75 anos ou mais", 75, None, 9),
    ("ignorada", "Idade ignorada", 0, None, 10),
]


def load_faixa_etaria() -> None:
    database_url = os.environ.get("DATABASE_URL_SYNC", "")
    if not database_url:
        raise RuntimeError("DATABASE_URL_SYNC environment variable is required")

    conn = psycopg2.connect(database_url)
    try:
        cur = conn.cursor()
        cur.executemany(
            """
            INSERT INTO dim_faixa_etaria (codigo, descricao, idade_min, idade_max, ordem)
            VALUES (%s, %s, %s, %s, %s)
            ON CONFLICT (codigo) DO UPDATE SET
                descricao = EXCLUDED.descricao,
                idade_min = EXCLUDED.idade_min,
                idade_max = EXCLUDED.idade_max,
                ordem = EXCLUDED.ordem
            """,
            FAIXAS,
        )
        conn.commit()
        cur.close()
        logger.info(f"faixa_etaria load complete: {len(FAIXAS)} rows loaded")
    finally:
        conn.close()


if __name__ == "__main__":
    load_faixa_etaria()
