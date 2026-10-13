"""SIH (Sistema de Informações Hospitalares) staging transformation.

Transforms raw DataSUS SIH columns into the canonical shape expected by the
fato_internacoes mart loader.

Architecture rule (non-negotiable):
    fato_internacoes must contain ONLY IDENT=1 (incident) AIHs.
    Long-stay continuation AIHs (IDENT=5) are filtered here and must
    never reach the database.  The assert after filtering is a hard safety net.

    IDENT, not SP_TIPO, is the correct incident discriminator: pysus 2.2.0
    concatenates the SIH-RD (AIH) and SIH-SP (procedures) groups into one
    DataFrame, and SP_TIPO belongs to the SP group — it is always null on
    genuine RD/AIH rows, so filtering on it drops 100% of incident AIHs.

    NOTE (pysus 2.7.0): IDENT=1 alone cannot distinguish RD ("AIH Reduzida",
    valid) from RJ ("AIH Rejeitada", rejected) records — both carry IDENT=1
    on ~100% of rows. RD isolation happens upstream, in
    etl.ingestor._fetch_sih_rd, via a filename-prefix filter applied to the
    catalog file list before download. The IDENT=1 filter below therefore
    remains a second, defense-in-depth layer against IDENT=5 long-stay
    continuation rows inside already-RD-filtered data, not the sole
    record-type discriminator.

No DB imports — this module is pure pandas transformation.
"""

import logging

import pandas as pd

logger = logging.getLogger(__name__)


def _parse_year(date_str: str) -> int | None:
    """Return the 4-digit year from an 8-char YYYYMMDD string, or None."""
    try:
        s = str(date_str).strip()
        if len(s) >= 4:
            return int(s[:4])
    except (ValueError, TypeError):
        pass
    return None


def _compute_idade_anos(
    nasc_series: pd.Series, dt_inter_series: pd.Series
) -> pd.Series:
    """Compute age in years as year(DT_INTER) - year(NASC).

    Both columns are YYYYMMDD strings.  Returns a nullable integer Series.
    Values outside [0, 120] are replaced with None.  Rows where either date
    is missing or unparseable are also returned as None.
    """

    def _calc(row: tuple) -> int | None:
        nasc_val, inter_val = row
        try:
            nasc_year = _parse_year(nasc_val)
            inter_year = _parse_year(inter_val)
            if nasc_year is None or inter_year is None:
                return None
            age = inter_year - nasc_year
            if 0 <= age <= 120:
                return age
            return None
        except Exception:
            return None

    pairs = list(zip(nasc_series, dt_inter_series))
    return pd.Series([_calc(p) for p in pairs], index=nasc_series.index, dtype="Int64")


def stage_sih(df: pd.DataFrame) -> pd.DataFrame:
    """Transform a raw DataSUS SIH DataFrame into the canonical staging shape.

    Expected input columns (DataSUS SIH RD format):
        N_AIH, DT_INTER, DT_SAIDA, DIAG_PRINC, MUNIC_RES, SEXO, NASC,
        IDENT, MORTE, VAL_TOT, QT_DIARIAS

    Output columns:
        aih_numero, sp_tipo, ano, mes, causa_basica, municipio_residencia,
        sexo, idade_anos, obitos_internacao, dias_permanencia, valor_total

    IDENT filter is applied FIRST and is followed by an assertion to confirm
    no non-incident AIHs survived. IDENT is coerced to numeric before
    comparison since pysus may surface it as a string ("1") depending on
    the source Parquet's dtype.

    Args:
        df: Raw SIH DataFrame as loaded from DataSUS FTP or sample Parquet.

    Returns:
        Staged DataFrame with the output columns listed above.

    Raises:
        AssertionError: If the IDENT filter failed and non-incident AIHs remain.
    """
    _COLS = [
        "IDENT",
        "N_AIH",
        "DT_INTER",
        "NASC",
        "DIAG_PRINC",
        "MUNIC_RES",
        "SEXO",
        "MORTE",
        "QT_DIARIAS",
        "VAL_TOT",
    ]
    df = df[[c for c in _COLS if c in df.columns]].copy()

    # ------------------------------------------------------------------
    # 1. IDENT filter — CRITICAL; must happen before any other work
    #    so that null-drop counts reflect only incident AIH rows.
    #    IDENT=1 is the incident (normal) AIH; IDENT=5 is a long-stay
    #    continuation. SP_TIPO must NOT be used here — see module docstring.
    # ------------------------------------------------------------------
    ident_numeric = pd.to_numeric(df["IDENT"], errors="coerce")
    n_non_incident = (ident_numeric != 1).sum()
    logger.info(
        "SIH: dropping %d non-incident AIHs (IDENT != 1) of %d total rows",
        n_non_incident,
        len(df),
    )
    df = df[ident_numeric == 1].copy()
    assert (pd.to_numeric(df["IDENT"], errors="coerce") == 1).all(), (
        "IDENT filter failed — non-incident AIHs remain"
    )

    # ------------------------------------------------------------------
    # 2. Drop rows with null key columns
    # ------------------------------------------------------------------
    before = len(df)
    df = df.dropna(subset=["DT_INTER"])
    n_dropped_dt = before - len(df)
    if n_dropped_dt:
        logger.info("SIH: dropped %d rows with null DT_INTER", n_dropped_dt)

    before = len(df)
    df = df.dropna(subset=["N_AIH"])
    n_dropped_aih = before - len(df)
    if n_dropped_aih:
        logger.info("SIH: dropped %d rows with null N_AIH", n_dropped_aih)

    before = len(df)
    df = df.dropna(subset=["MUNIC_RES"])
    n_dropped_munic = before - len(df)
    if n_dropped_munic:
        logger.info("SIH: dropped %d rows with null MUNIC_RES", n_dropped_munic)

    # ------------------------------------------------------------------
    # 3. Column mapping and transformations
    # ------------------------------------------------------------------

    # aih_numero: keep as string
    out = pd.DataFrame(index=df.index)
    out["aih_numero"] = df["N_AIH"].astype(str)

    # sp_tipo: mart invariant flag, not a raw DataSUS field — every surviving
    # row has already been confirmed incident by the IDENT filter above.
    out["sp_tipo"] = 1

    # ano and mes: parse 8-char YYYYMMDD string
    dt_inter_str = df["DT_INTER"].astype(str).str.strip()
    out["ano"] = (
        dt_inter_str.str[:4]
        .apply(lambda s: int(s) if s.isdigit() else None)
        .astype("Int64")
    )
    out["mes"] = (
        dt_inter_str.str[4:6]
        .apply(lambda s: int(s) if s.isdigit() else None)
        .astype("Int64")
    )

    # causa_basica: strip, uppercase, first 4 chars
    out["causa_basica"] = df["DIAG_PRINC"].astype(str).str.strip().str.upper().str[:4]

    # municipio_residencia: zero-pad to 6 digits
    out["municipio_residencia"] = df["MUNIC_RES"].apply(
        lambda v: str(v).split(".")[0].zfill(6)
    )

    # sexo: keep as string
    out["sexo"] = df["SEXO"].astype(str)

    # idade_anos: year(DT_INTER) - year(NASC); clamp [0, 120]; None if unparseable
    out["idade_anos"] = _compute_idade_anos(df["NASC"], df["DT_INTER"])

    # obitos_internacao: int (0 or 1), fill NA with 0
    out["obitos_internacao"] = (
        pd.to_numeric(df["MORTE"], errors="coerce").fillna(0).astype(int)
    )

    # dias_permanencia: int, None if missing
    out["dias_permanencia"] = (
        pd.to_numeric(df["QT_DIARIAS"], errors="coerce")
        .apply(lambda v: int(v) if pd.notna(v) else None)
        .astype("Int64")
    )

    # valor_total: float, None if missing
    out["valor_total"] = pd.to_numeric(df["VAL_TOT"], errors="coerce")

    logger.info(
        "SIH staging complete: %d incident AIH rows ready for mart loader",
        len(out),
    )

    return out.reset_index(drop=True)
