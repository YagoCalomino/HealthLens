"""SIM (Sistema de Informações sobre Mortalidade) staging transformation.

Normalizes raw DataSUS SIM columns to the intermediate staging schema used by
the mart loader. No DB imports — pure pandas transformation.
"""

import logging
import re
from typing import Optional

import pandas as pd

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger(__name__)

# Matches exactly 8 decimal digits (YYYYMMDD)
_DTOBITO_PATTERN = re.compile(r"^\d{8}$")


def _decode_idade(code) -> Optional[int]:
    """Decode DataSUS IDADE field to age in years.

    DataSUS age encoding:
    - code >= 400 → years (subtract 400)
    - code >= 300 → 0  (months encoding — infant under 1 year)
    - otherwise   → None (unknown or invalid)
    """
    if code is None:
        return None
    try:
        int_code = int(code)
    except (ValueError, TypeError):
        return None

    if int_code >= 400:
        return int_code - 400
    if int_code >= 300:
        return 0
    return None


def stage_sim(df: pd.DataFrame, uf: str = "", ano: int = 0) -> pd.DataFrame:
    """Normalize raw SIM DataFrame to staging schema.

    Accepts both the synthetic sample format (with NUMERODO/REVISAO columns) and
    the real pysus Parquet format (with CONTADOR only). When NUMERODO is absent,
    constructs a stable surrogate key as "DO{ano}{coduf}{CONTADOR:06d}".

    Drops rows that fail mandatory field checks and logs counts of dropped rows
    for each validation step. Returns a new DataFrame — the input is not mutated.

    Output columns (in order):
        numero_do, revisao_numero, ano, mes, causa_basica,
        municipio_residencia, sexo, idade_anos, raca_cor
    """
    original_count = len(df)
    result = df.copy()

    if "DTOBITO" not in result.columns or len(result) == 0:
        logger.warning(
            "stage_sim: DTOBITO column missing or empty DataFrame — returning empty"
        )
        return pd.DataFrame(
            columns=[
                "numero_do",
                "revisao_numero",
                "ano",
                "mes",
                "causa_basica",
                "municipio_residencia",
                "sexo",
                "idade_anos",
                "raca_cor",
            ]
        )

    # --- Validation: DTOBITO must be an 8-digit string ---
    dtobito_str = result["DTOBITO"].astype(str).str.strip()
    valid_dtobito = dtobito_str.str.match(r"^\d{8}$")
    # Also treat the string "None" or "nan" produced by astype(str) as invalid
    null_mask = result["DTOBITO"].isna()
    invalid_date_mask = null_mask | ~valid_dtobito
    n_dropped_date = int(invalid_date_mask.sum())
    if n_dropped_date:
        logger.info(
            "stage_sim: dropped %d rows with invalid or null DTOBITO (expected YYYYMMDD)",
            n_dropped_date,
        )
    result = result[~invalid_date_mask].copy()
    # Refresh the string series after filtering
    dtobito_str = result["DTOBITO"].astype(str).str.strip()

    # --- Validation: CAUSABAS must not be null or empty after stripping ---
    causabas_null = result["CAUSABAS"].isna()
    causabas_empty = result["CAUSABAS"].astype(str).str.strip() == ""
    invalid_causa_mask = causabas_null | causabas_empty
    n_dropped_causa = int(invalid_causa_mask.sum())
    if n_dropped_causa:
        logger.info(
            "stage_sim: dropped %d rows with null or empty CAUSABAS",
            n_dropped_causa,
        )
    result = result[~invalid_causa_mask].copy()
    dtobito_str = result["DTOBITO"].astype(str).str.strip()

    # --- Validation: CODMUNRES must not be null ---
    invalid_munres_mask = result["CODMUNRES"].isna()
    n_dropped_munres = int(invalid_munres_mask.sum())
    if n_dropped_munres:
        logger.info(
            "stage_sim: dropped %d rows with null CODMUNRES",
            n_dropped_munres,
        )
    result = result[~invalid_munres_mask].copy()
    dtobito_str = result["DTOBITO"].astype(str).str.strip()

    total_dropped = original_count - len(result)
    if total_dropped:
        logger.info(
            "stage_sim: total rows dropped: %d of %d (%.1f%%)",
            total_dropped,
            original_count,
            100.0 * total_dropped / original_count,
        )

    # --- Column transformations ---

    # Refresh dtobito_str on the final filtered frame
    dtobito_str = result["DTOBITO"].astype(str).str.strip()

    # Auto-detect DTOBITO byte order.
    # DataSUS SIM .dbc → pysus Parquet uses DDMMYYYY (e.g. "21042022").
    # Synthetic sample (generate_sample.py) uses YYYYMMDD (e.g. "20191209").
    #
    # Whole-batch scoring (mirrors the SINAN DT_NOTIFIC fix in sinan_staging.py):
    # score both format hypotheses across every row and pick whichever yields
    # more plausible calendar dates (year 1996-2030, month 1-12, day 1-31).
    # A single-row sniff (the prior approach) misfires whenever the sniffed
    # row's day-of-death is 20 — DD+MM concatenates to "20MM" (e.g. day=31,
    # month=12 -> "2012"), which looks like a valid year and misclassifies
    # the ENTIRE batch as YYYYMMDD. That silently corrupted `ano` for every
    # other row in the batch (e.g. a real Dec-31 death "31122022" produced
    # ano=3112 instead of 2022). Scoring the whole batch is immune to any
    # single outlier row.
    def _valid_date_count(
        s: pd.Series, ano_slice: tuple, mes_slice: tuple, dia_slice: tuple
    ) -> int:
        ano = pd.to_numeric(s.str.slice(*ano_slice), errors="coerce")
        mes = pd.to_numeric(s.str.slice(*mes_slice), errors="coerce")
        dia = pd.to_numeric(s.str.slice(*dia_slice), errors="coerce")
        return int(
            (ano.between(1996, 2030) & mes.between(1, 12) & dia.between(1, 31)).sum()
        )

    _yyyymmdd_score = _valid_date_count(dtobito_str, (0, 4), (4, 6), (6, 8))
    _ddmmyyyy_score = _valid_date_count(dtobito_str, (4, 8), (2, 4), (0, 2))

    if _yyyymmdd_score > _ddmmyyyy_score:
        # Sample data: YYYYMMDD
        def _get_ano(s):
            return s.str[:4].astype(int)

        def _get_mes(s):
            return s.str[4:6].astype(int)
    else:
        # Real DataSUS SIM: DDMMYYYY (also the default on a tie)
        def _get_ano(s):
            return s.str[4:8].astype(int)

        def _get_mes(s):
            return s.str[2:4].astype(int)

    staged = pd.DataFrame()

    # --- numero_do: real pysus data has CONTADOR; synthetic sample has NUMERODO ---
    if "NUMERODO" in result.columns:
        staged["numero_do"] = result["NUMERODO"].astype(str)
    else:
        # Derive a 2-digit UF code from the first 2 chars of CODMUNRES for the key.
        # If the caller supplied uf/ano, prefer those for a stable surrogate.
        coduf = str(ano)[-2:] if not uf else ""
        if "CODUF" in result.columns:
            coduf_series = result["CODUF"].astype(str).str.zfill(2)
        elif "CODMUNRES" in result.columns:
            coduf_series = result["CODMUNRES"].astype(str).str[:2]
        else:
            coduf_series = pd.Series(coduf, index=result.index)
        counter_series = result.get(
            "CONTADOR", pd.Series(range(1, len(result) + 1), index=result.index)
        ).astype(int)
        staged["numero_do"] = (
            "DO" + str(ano) + coduf_series + counter_series.apply(lambda x: f"{x:06d}")
        )

    # REVISAO: only present in synthetic sample data; default to 0 for real data
    staged["revisao_numero"] = (
        result["REVISAO"].fillna(0).astype(int) if "REVISAO" in result.columns else 0
    )
    staged["ano"] = _get_ano(dtobito_str)
    staged["mes"] = _get_mes(dtobito_str)
    staged["causa_basica"] = (
        result["CAUSABAS"].astype(str).str.strip().str.upper().str[:4]
    )
    staged["municipio_residencia"] = (
        result["CODMUNRES"].astype(str).str.strip().apply(lambda v: v.zfill(6))
    )
    staged["sexo"] = result["SEXO"].astype(str)
    staged["idade_anos"] = result["IDADE"].apply(_decode_idade)

    # raca_cor: raw single-character DataSUS RACACOR code, stored as-is.
    # RACACOR is absent from synthetic sample data and every existing test
    # fixture — tolerate the missing column instead of raising KeyError.
    if "RACACOR" in result.columns:
        _racacor_raw = result["RACACOR"].astype(str).str.strip()
        _blank_mask = (_racacor_raw == "") | _racacor_raw.str.lower().isin(
            ["nan", "none"]
        )
        staged["raca_cor"] = _racacor_raw.str[:1].where(~_blank_mask, None)
    else:
        staged["raca_cor"] = None

    return staged[
        [
            "numero_do",
            "revisao_numero",
            "ano",
            "mes",
            "causa_basica",
            "municipio_residencia",
            "sexo",
            "idade_anos",
            "raca_cor",
        ]
    ]


def compute_faixa_etaria_codigo(idade_anos: Optional[int]) -> str:
    """Map age in years to dim_faixa_etaria.codigo.

    Buckets match the 10 standard Brazilian health age groups seeded into
    dim_faixa_etaria by seeds/faixa_etaria_loader.py.
    """
    if idade_anos is None:
        return "ignorada"
    if idade_anos <= 4:
        return "0_4"
    if idade_anos <= 14:
        return "5_14"
    if idade_anos <= 24:
        return "15_24"
    if idade_anos <= 34:
        return "25_34"
    if idade_anos <= 44:
        return "35_44"
    if idade_anos <= 54:
        return "45_54"
    if idade_anos <= 64:
        return "55_64"
    if idade_anos <= 74:
        return "65_74"
    return "75_mais"
