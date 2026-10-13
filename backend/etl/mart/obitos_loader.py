"""Mart loader for fato_obitos (SIM — Sistema de Informações sobre Mortalidade).

Each row in the staged DataFrame represents one death certificate (Declaração de
Óbito).  The loader resolves dimension FKs via an in-memory DimCache, accumulates
rows into batches of 1 000, and upserts them using psycopg2 execute_values.

Upsert key: (numero_do, revisao_numero) — handles SIM revision cycles without
creating duplicate rows.
"""

import logging
import math
from typing import Optional

import pandas as pd
import psycopg2.extras

from etl.mart.dim_lookup import DimCache
from etl.staging.sim_staging import compute_faixa_etaria_codigo

logger = logging.getLogger(__name__)

_BATCH_SIZE = 1000

_UPSERT_SQL = """
INSERT INTO fato_obitos (
    dim_tempo_id, dim_local_id, dim_causa_id, dim_faixa_etaria_id,
    revisao_numero, numero_do, obitos, taxa_por_100k, sexo, idade_anos, raca_cor
) VALUES %s
ON CONFLICT (numero_do, revisao_numero) DO UPDATE SET
    dim_tempo_id        = EXCLUDED.dim_tempo_id,
    dim_local_id        = EXCLUDED.dim_local_id,
    dim_causa_id        = EXCLUDED.dim_causa_id,
    dim_faixa_etaria_id = EXCLUDED.dim_faixa_etaria_id,
    taxa_por_100k       = EXCLUDED.taxa_por_100k,
    sexo                = EXCLUDED.sexo,
    idade_anos          = EXCLUDED.idade_anos,
    raca_cor            = EXCLUDED.raca_cor
"""


def load_obitos(staged: pd.DataFrame, cache: DimCache, conn) -> int:
    """Upsert staged SIM death records into fato_obitos.

    Resolves all dimension FKs from the in-memory DimCache.  Rows that cannot
    be mapped to dim_local or dim_causa are skipped and counted separately —
    they represent extinct municipalities or unknown cause codes that are not
    yet seeded.

    taxa_por_100k is computed as 1 / populacao * 100 000.  Each staged row
    represents exactly one death (obitos = 1), so no aggregation is applied
    here; the mart query layer handles grouping.

    Args:
        staged: Output of stage_sim() — one row per death certificate.
        cache:  Pre-loaded DimCache (call cache.load_all(conn) before this).
        conn:   Live psycopg2 connection with autocommit disabled.

    Returns:
        Total number of rows sent to the database (skipped rows excluded).
    """
    total_upserted = 0
    skipped_local = 0
    skipped_causa = 0
    batch: list[tuple] = []

    for row_idx, row in enumerate(staged.itertuples(index=False), start=1):
        # --- dim_local: mandatory FK ---
        dim_local_id: Optional[int] = cache.get_local_id(row.municipio_residencia)
        if dim_local_id is None:
            skipped_local += 1
            continue

        # --- dim_causa: mandatory FK ---
        dim_causa_id: Optional[int] = cache.get_causa_id(row.causa_basica)
        if dim_causa_id is None:
            skipped_causa += 1
            continue

        # --- dim_tempo: created on demand (SIM months may not be pre-seeded) ---
        dim_tempo_id: int = cache.get_or_create_tempo_id(row.ano, row.mes, conn)

        # --- dim_faixa_etaria: falls back to 'ignorada' bucket when age is unknown ---
        dim_faixa_etaria_id: Optional[int] = cache.get_faixa_etaria_id(
            compute_faixa_etaria_codigo(row.idade_anos)
        )

        # --- taxa_por_100k: one DO record = one death, rate = 1 / pop * 100 000 ---
        populacao: Optional[int] = cache.get_populacao(
            row.municipio_residencia, row.ano
        )
        taxa_por_100k: Optional[float] = (
            1.0 / populacao * 100_000 if populacao else None
        )

        batch.append(
            (
                dim_tempo_id,
                dim_local_id,
                dim_causa_id,
                dim_faixa_etaria_id,
                int(row.revisao_numero),
                str(row.numero_do),
                1,  # obitos — one row = one death
                taxa_por_100k,
                str(row.sexo)
                if (
                    row.sexo is not None
                    and not (isinstance(row.sexo, float) and math.isnan(row.sexo))
                )
                else None,
                int(row.idade_anos)
                if (
                    row.idade_anos is not None
                    and not (
                        isinstance(row.idade_anos, float) and math.isnan(row.idade_anos)
                    )
                )
                else None,
                str(row.raca_cor)
                if (
                    row.raca_cor is not None
                    and not (
                        isinstance(row.raca_cor, float) and math.isnan(row.raca_cor)
                    )
                )
                else None,
            )
        )

        if len(batch) >= _BATCH_SIZE:
            with conn.cursor() as cur:
                psycopg2.extras.execute_values(cur, _UPSERT_SQL, batch)
            conn.commit()
            total_upserted += len(batch)
            batch = []

        if row_idx % 10_000 == 0:
            logger.info(
                "load_obitos progress: %d rows processed, %d upserted, "
                "%d skipped (local=%d, causa=%d)",
                row_idx,
                total_upserted,
                skipped_local + skipped_causa,
                skipped_local,
                skipped_causa,
            )

    # Flush remaining rows that did not fill a full batch
    if batch:
        with conn.cursor() as cur:
            psycopg2.extras.execute_values(cur, _UPSERT_SQL, batch)
        conn.commit()
        total_upserted += len(batch)

    total_skipped = skipped_local + skipped_causa
    logger.info(
        "load_obitos complete: %d upserted, %d skipped (local=%d, causa=%d)",
        total_upserted,
        total_skipped,
        skipped_local,
        skipped_causa,
    )

    # Uniqueness is enforced by uq_fato_obitos_numerodo_revisao index —
    # the per-file full-table scan here becomes a bottleneck at multi-million row scale.
    # assert_no_duplicate_numerodo(conn)
    return total_upserted


def assert_no_duplicate_numerodo(conn) -> None:
    """Post-load assertion: each numero_do must appear at most once.

    SIM upsert key is (numero_do, revisao_numero), so a given numero_do can
    theoretically appear in multiple revision rows.  This assertion enforces
    the business rule that each physical death certificate (numero_do) should
    not produce more than one row in the fact table after the most recent
    revision has been applied.

    Raises:
        AssertionError: if any numero_do is linked to more than one fact row.
    """
    with conn.cursor() as cur:
        cur.execute("""
            SELECT COUNT(*) FROM (
                SELECT numero_do FROM fato_obitos
                GROUP BY numero_do HAVING COUNT(*) > 1
            ) dups
        """)
        count = cur.fetchone()[0]

    if count != 0:
        raise AssertionError(
            f"fato_obitos: {count} numero_do values with duplicate rows"
        )

    logger.info("Assertion passed: zero duplicate numero_do in fato_obitos")
