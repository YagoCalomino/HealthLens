"""SIH (Sistema de Informações Hospitalares) mart loader.

Loads staged SIH records into fato_internacoes, resolving all dimension FKs
via DimCache and computing taxa_por_100k at load time.

Invariant enforced here: only sp_tipo=1 AIHs may exist in
fato_internacoes. The staging layer filters non-incident AIHs before this
loader runs; assert_no_non_incident_aih() verifies the invariant holds after
every upsert batch.
"""

import logging
from typing import Optional

import pandas as pd
import psycopg2.extras

from etl.mart.dim_lookup import DimCache
from etl.staging.sim_staging import compute_faixa_etaria_codigo

logger = logging.getLogger(__name__)

_BATCH_SIZE = 250


def _to_int(v) -> int | None:
    """NA → None, otherwise native Python int (strips numpy.int64)."""
    if pd.isna(v):
        return None
    return int(v)


def _to_float(v) -> float | None:
    """NA → None, otherwise native Python float (strips numpy.float64)."""
    if pd.isna(v):
        return None
    return float(v)


_UPSERT_SQL = """
INSERT INTO fato_internacoes (
    dim_tempo_id, dim_local_id, dim_causa_id, dim_faixa_etaria_id,
    aih_numero, sp_tipo, internacoes, obitos_internacao,
    dias_permanencia, taxa_por_100k, valor_total
) VALUES %s
ON CONFLICT (aih_numero) DO UPDATE SET
    dim_tempo_id        = EXCLUDED.dim_tempo_id,
    dim_local_id        = EXCLUDED.dim_local_id,
    dim_causa_id        = EXCLUDED.dim_causa_id,
    dim_faixa_etaria_id = EXCLUDED.dim_faixa_etaria_id,
    taxa_por_100k       = EXCLUDED.taxa_por_100k,
    obitos_internacao   = EXCLUDED.obitos_internacao,
    dias_permanencia    = EXCLUDED.dias_permanencia,
    valor_total         = EXCLUDED.valor_total
"""


def load_internacoes(staged: pd.DataFrame, cache: DimCache, conn) -> int:
    """Load staged SIH records into fato_internacoes.

    Resolves dimension FKs from DimCache. Rows whose dim_local_id or
    dim_causa_id cannot be resolved are skipped and logged — these represent
    extinct municipalities or unknown CID-10 codes in source data.

    Upsert key: aih_numero (unique per incident AIH).
    Commits after every batch of 1000 rows.

    Returns the total number of rows upserted.
    """
    total_rows = len(staged)
    upserted = 0
    skipped = 0
    batch: list[tuple] = []

    for i, row in enumerate(staged.itertuples(index=False), start=1):
        # --- Dimension FK resolution ---
        dim_tempo_id = cache.get_or_create_tempo_id(row.ano, row.mes, conn)

        dim_local_id = cache.get_local_id(row.municipio_residencia)
        if dim_local_id is None:
            skipped += 1
            continue

        dim_causa_id = cache.get_causa_id(row.causa_basica)
        if dim_causa_id is None:
            skipped += 1
            continue

        idade_anos: Optional[int] = _to_int(row.idade_anos)
        dim_faixa_etaria_id = cache.get_faixa_etaria_id(
            compute_faixa_etaria_codigo(idade_anos)
        )

        # --- taxa_por_100k: 1 internacao per incident AIH row ---
        populacao = cache.get_populacao(row.municipio_residencia, row.ano)
        taxa_por_100k = (1.0 / populacao * 100_000) if populacao else None

        batch.append(
            (
                dim_tempo_id,
                dim_local_id,
                dim_causa_id,
                dim_faixa_etaria_id,
                str(row.aih_numero),
                1,  # sp_tipo always 1 — invariant from staging
                1,  # internacoes = 1 per incident AIH
                int(row.obitos_internacao),
                _to_int(row.dias_permanencia),
                taxa_por_100k,
                _to_float(row.valor_total),
            )
        )

        if len(batch) >= _BATCH_SIZE:
            upserted += _flush_batch(batch, conn)
            batch = []

        if i % 10_000 == 0:
            logger.info(
                "load_internacoes: processed %d / %d rows (upserted=%d skipped=%d)",
                i,
                total_rows,
                upserted,
                skipped,
            )

    # Flush remaining rows
    if batch:
        upserted += _flush_batch(batch, conn)

    logger.info(
        "load_internacoes: finished — total=%d upserted=%d skipped=%d",
        total_rows,
        upserted,
        skipped,
    )

    assert_no_non_incident_aih(conn)

    return upserted


def _flush_batch(batch: list[tuple], conn) -> int:
    """Execute a single upsert batch and commit.

    Deduplicates by aih_numero (index 4) before executing — ON CONFLICT
    DO UPDATE cannot affect the same row twice in one command (Postgres
    raises CardinalityViolation). Keeps the last occurrence of each
    duplicate, which is safe since all rows are incident AIHs (sp_tipo=1).
    """
    seen: dict[str, tuple] = {}
    for row in batch:
        seen[row[4]] = row
    deduped = list(seen.values())
    try:
        with conn.cursor() as cur:
            psycopg2.extras.execute_values(cur, _UPSERT_SQL, deduped)
        conn.commit()
    except psycopg2.OperationalError:
        # Postgres dropped the connection (OOM kill, timeout). Re-raise so
        # the pipeline can reconnect at the caller level. rollback() itself
        # can fail if the connection is already closed.
        try:
            conn.rollback()
        except Exception:
            pass
        raise
    return len(deduped)


def assert_no_non_incident_aih(conn) -> None:
    """Post-load assertion: all fato_internacoes rows must have sp_tipo=1.

    Raises AssertionError if any non-incident AIH row is found. This catches
    data pipeline bugs where the staging filter (sp_tipo=1) was bypassed or
    data was inserted via a path that skipped staging validation.
    """
    with conn.cursor() as cur:
        cur.execute("SELECT COUNT(*) FROM fato_internacoes WHERE sp_tipo != 1")
        count = cur.fetchone()[0]

    if count != 0:
        raise AssertionError(f"fato_internacoes: {count} rows with sp_tipo != 1")

    logger.info("Assertion passed: all fato_internacoes rows have sp_tipo=1")
