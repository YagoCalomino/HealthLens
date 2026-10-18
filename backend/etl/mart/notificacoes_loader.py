"""Mart loader for fato_notificacoes (SINAN — Sistema de Informação de Agravos
de Notificação, agravos DENG/CHIK/ANIM).

Each row in the staged DataFrame represents one SINAN notificação — never an
asserted confirmed case. Confirmation status is carried separately as the
raw classi_fin code (raw codes only, decode lives in
app/constants/sinan.py) and must be filtered explicitly by any consumer that
wants confirmed-only counts. Do not conflate
"notificação" with "caso confirmado" anywhere in this module.

The loader resolves dimension FKs via an in-memory DimCache, accumulates
rows into batches of 1 000, and upserts them using psycopg2 execute_values.

Upsert key: (numero_notificacao, tipo_agravo) — the composite natural key,
because SINAN has no reliable single-column dedup key across the three
agravos sharing one physical fact table (NU_NOTIFIC is
absent from all three live source frames; stage_sinan builds a
deterministic surrogate numero_notificacao instead).
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
INSERT INTO fato_notificacoes (
    dim_tempo_id, dim_local_id, dim_agravo_id, dim_faixa_etaria_id,
    tipo_agravo, numero_notificacao, notificacoes, taxa_por_100k, sexo,
    idade_anos, classi_fin, gravidade_grave, tra_classi, tp_acidente,
    dt_notific
) VALUES %s
ON CONFLICT (numero_notificacao, tipo_agravo) DO UPDATE SET
    dim_tempo_id        = EXCLUDED.dim_tempo_id,
    dim_local_id        = EXCLUDED.dim_local_id,
    dim_agravo_id       = EXCLUDED.dim_agravo_id,
    dim_faixa_etaria_id = EXCLUDED.dim_faixa_etaria_id,
    taxa_por_100k       = EXCLUDED.taxa_por_100k,
    sexo                = EXCLUDED.sexo,
    idade_anos          = EXCLUDED.idade_anos,
    classi_fin          = EXCLUDED.classi_fin,
    gravidade_grave     = EXCLUDED.gravidade_grave,
    tra_classi          = EXCLUDED.tra_classi,
    tp_acidente         = EXCLUDED.tp_acidente,
    dt_notific          = EXCLUDED.dt_notific
"""


def _nan_safe(value, cast):
    """Cast a staged scalar to `cast`, mapping None/NaN to None.

    Mirrors obitos_loader.py's inline math.isnan guard idiom — pandas
    itertuples() surfaces missing values in object columns as either a
    real None or the float nan, never consistently one or the other.
    """
    if value is None:
        return None
    if isinstance(value, float) and math.isnan(value):
        return None
    return cast(value)


def _nan_safe_bool(value) -> Optional[bool]:
    """Cast a staged gravidade_grave value to bool, None-safe.

    A pandas object column mixing real bools and None will not survive a
    bare bool() cast (bool(None) raises inside int()/etc. call chains
    elsewhere, and bool(float('nan')) is truthy) — pd.isna() is required
    here in addition to the plain None check.
    """
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return None
    if pd.isna(value):
        return None
    return bool(value)


def _nan_safe_date(value):
    """Cast a staged dt_notific value to a plain date, None-safe.

    Mirrors _nan_safe_bool's pd.isna() guard — a pandas object column mixing
    real datetime.date values and NaT/None does not survive a bare cast.
    psycopg2 adapts datetime.date natively, so the value travels as-is
    rather than as a string.
    """
    if value is None:
        return None
    if isinstance(value, float) and math.isnan(value):
        return None
    if pd.isna(value):
        return None
    return value


def load_notificacoes(staged: pd.DataFrame, cache: DimCache, conn) -> int:
    """Upsert staged SINAN notification rows into fato_notificacoes.

    Resolves all four dimension FKs from the in-memory DimCache. Rows that
    cannot be mapped to dim_local (residence municipality) or dim_agravo are
    skipped and counted separately — they represent extinct/unseeded
    municipalities or a programming-error tipo_agravo respectively.

    taxa_por_100k is computed as 1 / populacao * 100 000 at load time (locked
    architecture decision — the API must never JOIN population
    at query time). Each staged row represents exactly one notification
    (notificacoes = 1), so no aggregation is applied here.

    Args:
        staged: Output of stage_sinan() — one row per SINAN notification.
        cache:  Pre-loaded DimCache (call cache.load_all(conn) before this).
        conn:   Live psycopg2 connection with autocommit disabled.

    Returns:
        Total number of rows sent to the database (skipped rows excluded).
    """
    total_upserted = 0
    skipped_local = 0
    skipped_agravo = 0
    batch: list[tuple] = []

    for row_idx, row in enumerate(staged.itertuples(index=False), start=1):
        # --- dim_local: mandatory FK, resolved from RESIDENCE, never the
        # notifying-unit code. row.municipio_residencia already carries
        # ID_MN_RESI, not ID_MUNICIP — stage_sinan guarantees
        # this at staging time. ---
        dim_local_id: Optional[int] = cache.get_local_id(row.municipio_residencia)
        if dim_local_id is None:
            skipped_local += 1
            continue

        # --- dim_agravo: mandatory FK ---
        dim_agravo_id: Optional[int] = cache.get_agravo_id(row.tipo_agravo)
        if dim_agravo_id is None:
            skipped_agravo += 1
            continue

        # --- dim_tempo: created on demand ---
        dim_tempo_id: int = cache.get_or_create_tempo_id(row.ano, row.mes, conn)

        # --- dim_faixa_etaria: falls back to 'ignorada' bucket when age is unknown ---
        dim_faixa_etaria_id: Optional[int] = cache.get_faixa_etaria_id(
            compute_faixa_etaria_codigo(row.idade_anos)
        )

        # --- taxa_por_100k: one staged row = one notification, rate = 1 / pop * 100 000 ---
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
                dim_agravo_id,
                dim_faixa_etaria_id,
                str(row.tipo_agravo),
                str(row.numero_notificacao),
                1,  # notificacoes — one row = one notificação
                taxa_por_100k,
                _nan_safe(row.sexo, str),
                _nan_safe(row.idade_anos, int),
                _nan_safe(row.classi_fin, int),
                _nan_safe_bool(row.gravidade_grave),
                _nan_safe(row.tra_classi, int),
                _nan_safe(row.tp_acidente, int),
                _nan_safe_date(row.dt_notific),
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
                "load_notificacoes progress: %d rows processed, %d upserted, "
                "%d skipped (local=%d, agravo=%d)",
                row_idx,
                total_upserted,
                skipped_local + skipped_agravo,
                skipped_local,
                skipped_agravo,
            )

    # Flush remaining rows that did not fill a full batch
    if batch:
        with conn.cursor() as cur:
            psycopg2.extras.execute_values(cur, _UPSERT_SQL, batch)
        conn.commit()
        total_upserted += len(batch)

    total_skipped = skipped_local + skipped_agravo
    logger.info(
        "load_notificacoes complete: %d upserted, %d skipped (local=%d, agravo=%d)",
        total_upserted,
        total_skipped,
        skipped_local,
        skipped_agravo,
    )

    # Uniqueness is enforced by the fato_notificacoes uq_numero_notificacao_tipo_agravo
    # index — SINAN's completeness gate is the standalone
    # scripts/assert_sinan_completeness.py, not a per-file
    # full-table scan here (same scaling rationale as obitos_loader.py).
    return total_upserted
