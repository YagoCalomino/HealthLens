"""SINAN (Sistema de Informação de Agravos de Notificação) staging transformation.

Normalizes raw DataSUS SINAN columns (DENG/CHIK/ANIM) to the intermediate
staging schema consumed by the mart loader (load_notificacoes).
Pure pandas transformation — no DB imports.

Geographic attribution is always by ID_MN_RESI (município of residence),
never the notifying-unit column (see the comment above the
municipio_residencia assignment in stage_sinan for the rationale). UF-level attribution is resolved downstream via
dim_local, never from the raw UF columns in the source
DataFrame, because those columns hold 2-digit IBGE numeric UF codes (e.g.
'35') rather than 2-letter siglas ('SP') — a naive sigla comparison would
silently match zero rows.
"""

import hashlib
import logging

import pandas as pd

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger(__name__)

STAGED_COLUMNS = [
    "numero_notificacao",
    "tipo_agravo",
    "ano",
    "mes",
    "dt_notific",
    "municipio_residencia",
    "sexo",
    "idade_anos",
    "classi_fin",
    "gravidade_grave",
    "tra_classi",
    "tp_acidente",
]

DENG_CHIK_AGRAVOS = ("DENG", "CHIK")

# Live-verified (docs/pysus-270-sinan-spike-findings.md): DataSUS SINAN Parquet output represents "missing" as both a
# true empty string and, separately, the literal 4-character string "None"
# — two distinct value_counts buckets, not one. pd.isna() alone misses the
# second case.
_MISSING_TOKENS = ("", "nan", "none")

# Full 15-member DENG/CHIK "sinais de gravidade" family (dengue grave,
# structurally gated to CLASSI_FIN=12). Absent entirely from ANIM's real
# columns — not merely null there. See the module-level comment on the
# ANIM-side counterpart (TRA_CLASSI/TP_ACIDENT).
GRAV_COLUMNS = (
    "GRAV_PULSO",
    "GRAV_CONV",
    "GRAV_ENCH",
    "GRAV_INSUF",
    "GRAV_TAQUI",
    "GRAV_EXTRE",
    "GRAV_HIPOT",
    "GRAV_HEMAT",
    "GRAV_MELEN",
    "GRAV_METRO",
    "GRAV_SANG",
    "GRAV_AST",
    "GRAV_MIOC",
    "GRAV_CONSC",
    "GRAV_ORGAO",
)
ANIM_COLUMNS = ("TP_ACIDENT", "TRA_CLASSI")


def _blank_mask(series: pd.Series) -> pd.Series:
    """Return a boolean mask of values that are null or a known missing token.

    Stripped + lowercased string form in _MISSING_TOKENS, or NA — catches
    both the true-empty-string and literal-"None"-string missing shapes.
    """
    isna_mask = series.isna()
    stripped = series.astype(str).str.strip().str.lower()
    return isna_mask | stripped.isin(_MISSING_TOKENS)


def _raw_code_to_int(series: pd.Series) -> pd.Series:
    """Coerce a raw DataSUS numeric-code column to Python ints or None.

    Applies _blank_mask first (empty string / literal "None" -> None), then
    int(float(v)) inside a try/except that yields None on any failure. Used
    for classi_fin, tra_classi and tp_acidente, all of which target SMALLINT
    columns in fato_notificacoes.
    """
    blank = _blank_mask(series)

    def _conv(v):
        try:
            return int(float(v))
        except (ValueError, TypeError):
            return None

    converted = series.apply(_conv).astype(object)
    converted[blank] = None
    return converted


def _decode_idade_sinan(code) -> "int | None":
    """Decode SINAN's NU_IDADE_N 4-digit age encoding to years.

    Leading digit 4 means years (code - 4000); leading digits 1/2/3 mean
    hours/days/months respectively, and therefore age 0; anything else, or
    an unparseable value, or a decoded age above 120, returns None.

    This encoding is NOT the same as SIM's IDADE field (sim_staging.py's
    _decode_idade, which uses a 400-offset) and must not be shared with it.
    The observed NU_IDADE_N distribution was confirmed against
    docs/pysus-270-sinan-spike-findings.md before this decoder was written.
    """
    if code is None or (isinstance(code, float) and pd.isna(code)):
        return None
    try:
        int_code = int(float(code))
    except (ValueError, TypeError):
        return None

    leading = int_code // 1000
    if leading == 4:
        age = int_code - 4000
    elif leading in (1, 2, 3):
        age = 0
    else:
        return None

    if age < 0 or age > 120:
        return None
    return age


def _parse_dt_notific(series: pd.Series) -> pd.Series:
    """Parse DT_NOTIFIC to a datetime Series.

    pysus's parse_dftypes already converts DT_NOTIFIC to datetime64 on some
    years and leaves it as an 8-digit string on others — both shapes must
    work. When already datetime64, use it directly.

    When it is an 8-digit string, the digit *order* is not fixed across
    agravos/years: live-verified against real DataSUS SINAN data, ANIM
    2023's DT_NOTIFIC is YYYYMMDD (e.g. "20230101"), not the DDMMYYYY shape
    `sim_staging.py`'s equivalent SIM field uses. Blindly assuming DDMMYYYY
    silently drops every row once the day-as-month component overflows month
    12 (`pd.to_datetime` coerces to NaT rather than raising) — exactly the
    failure the live run caught.
    Detect the real order per-batch instead of assuming one: try both
    `%d%m%Y` and `%Y%m%d` against the batch's 8-digit values and count how
    many each actually parses to a valid calendar date. `%d%m%Y` is the
    default/tie-break winner (matches the project's established SIM
    convention and the existing unit fixtures) — `%Y%m%d` is only chosen
    when it strictly out-parses `%d%m%Y` on this batch, which is what real
    YYYYMMDD-shaped data (e.g. ANIM) does.
    """
    if pd.api.types.is_datetime64_any_dtype(series):
        return pd.to_datetime(series, errors="coerce")

    str_series = series.astype(str).str.strip()
    non_blank = str_series[~_blank_mask(series)]
    if len(non_blank) > 0:
        digit8 = non_blank[non_blank.str.match(r"^\d{8}$")]
        if len(digit8) > 0 and len(digit8) / len(non_blank) >= 0.5:
            ddmmyyyy_hits = (
                pd.to_datetime(digit8, format="%d%m%Y", errors="coerce").notna().sum()
            )
            yyyymmdd_hits = (
                pd.to_datetime(digit8, format="%Y%m%d", errors="coerce").notna().sum()
            )
            fmt = "%Y%m%d" if yyyymmdd_hits > ddmmyyyy_hits else "%d%m%Y"
            return pd.to_datetime(str_series, format=fmt, errors="coerce")
    return pd.to_datetime(str_series, errors="coerce")


def _build_numero_notificacao(
    result: pd.DataFrame,
    staged: pd.DataFrame,
    tipo_agravo: str,
    ordinal_offsets: dict[str, int] | None = None,
) -> pd.Series:
    """Build a deterministic, within-file-unique notification key.

    SINAN has no guaranteed unique single-column dedup key — NU_NOTIFIC was
    confirmed absent from all three live agravo frames (docs/pysus-270-sinan-spike-findings.md), so a deterministic
    composite is built instead:

    - base: NU_NOTIFIC when that column exists and is not blank per
      _blank_mask; otherwise the concatenation of staged ano (4 digits),
      mes (2 digits) and municipio_residencia (6 digits).
    - key_base: f"{ano}{base}" — prefixed with the staged year so the same
      base can never collide across years.
    - When key_base exceeds 32 characters, it is replaced with
      "H" + md5(key_base).hexdigest()[:31] to respect the <= 40 char limit.
    - A within-file duplicate ordinal (groupby(key_base).cumcount()) is
      always appended as f"{key_base}-{ordinal}" — "-0" for the common
      unique case.

    This guarantees uniqueness within one source file and byte-identical
    keys on re-load of the same cached Parquet. When a file is staged in
    chunks, the caller passes one ordinal_offsets dict for the whole file:
    without it the ordinal restarts at 0 in every chunk and keys collide
    across chunks (the upsert then silently overwrote ~32% of DENG 2025).
    The dict is updated in place with each key_base's running count, so
    chunked keys are identical to whole-file keys. A genuine duplicate across
    a PRELIM file and its later FINAL file of the same year is a known,
    accepted limitation covered by the known_partial allowlist mechanism in
    scripts/assert_sinan_completeness.py — not silently ignored.
    """
    ano_str = staged["ano"].astype(int).astype(str).str.zfill(4)
    mes_str = staged["mes"].astype(int).astype(str).str.zfill(2)
    muni_str = staged["municipio_residencia"].astype(str)
    fallback_base = ano_str + mes_str + muni_str

    if "NU_NOTIFIC" in result.columns:
        nu_notific = result["NU_NOTIFIC"]
        nu_blank = _blank_mask(nu_notific)
        nu_str = nu_notific.astype(str).str.strip()
        base = nu_str.where(~nu_blank, fallback_base)
    else:
        base = fallback_base

    key_base = ano_str + base.astype(str)

    def _shorten(k: str) -> str:
        if len(k) > 32:
            return "H" + hashlib.md5(k.encode("utf-8")).hexdigest()[:31]
        return k

    key_base = key_base.apply(_shorten)
    ordinal = key_base.groupby(key_base).cumcount()

    if ordinal_offsets is not None:
        ordinal = ordinal + key_base.map(ordinal_offsets).fillna(0).astype(int)
        for k, n in key_base.value_counts().items():
            ordinal_offsets[k] = ordinal_offsets.get(k, 0) + int(n)

    return key_base + "-" + ordinal.astype(str)


def stage_sinan(
    df: pd.DataFrame,
    tipo_agravo: str,
    ordinal_offsets: dict[str, int] | None = None,
) -> pd.DataFrame:
    """Normalize a raw SINAN DataFrame to the staging schema.

    Branches its column selection by tipo_agravo (DENG/CHIK vs ANIM) since
    those two column families are physically disjoint in the real DataSUS
    export — see the per-agravo branch below.

    Output columns, in order: see STAGED_COLUMNS.

    ordinal_offsets: pass the same dict for every chunk of one source file
    (see _build_numero_notificacao); omit when staging a whole file at once.
    """
    tipo_agravo = tipo_agravo.strip().upper()
    original_count = len(df)

    if len(df) == 0 or "DT_NOTIFIC" not in df.columns or "ID_MN_RESI" not in df.columns:
        logger.warning(
            "stage_sinan: empty DataFrame or missing DT_NOTIFIC/ID_MN_RESI — returning empty"
        )
        return pd.DataFrame(columns=STAGED_COLUMNS)

    result = df.copy()

    # --- Validation: ID_MN_RESI (residence) must not be null/blank ---
    invalid_resi_mask = _blank_mask(result["ID_MN_RESI"])
    n_dropped_resi = int(invalid_resi_mask.sum())
    if n_dropped_resi:
        logger.info(
            "stage_sinan: dropped %d rows with null/blank ID_MN_RESI", n_dropped_resi
        )
    result = result[~invalid_resi_mask].copy()

    # --- Validation: DT_NOTIFIC must parse to a real date ---
    parsed_dates = _parse_dt_notific(result["DT_NOTIFIC"])
    invalid_date_mask = parsed_dates.isna()
    n_dropped_date = int(invalid_date_mask.sum())
    if n_dropped_date:
        logger.info(
            "stage_sinan: dropped %d rows with unparseable DT_NOTIFIC", n_dropped_date
        )
    result = result[~invalid_date_mask].copy()
    parsed_dates = parsed_dates[~invalid_date_mask]

    total_dropped = original_count - len(result)
    if total_dropped:
        logger.info(
            "stage_sinan: total rows dropped: %d of %d (%.1f%%)",
            total_dropped,
            original_count,
            100.0 * total_dropped / original_count,
        )

    if len(result) == 0:
        return pd.DataFrame(columns=STAGED_COLUMNS)

    staged = pd.DataFrame(index=result.index)
    staged["ano"] = parsed_dates.dt.year.astype(int)
    staged["mes"] = parsed_dates.dt.month.astype(int)
    # dt_notific comes from the same parsed_dates Series as ano/mes (single
    # parse) — never re-derived, so the three can never disagree.
    staged["dt_notific"] = parsed_dates.dt.date
    # Residence attribution — ID_MN_RESI, NOT
    # ID_MUNICIP (the notifying health unit). ID_MUNICIP is never read here.
    staged["municipio_residencia"] = (
        result["ID_MN_RESI"].astype(str).str.strip().str.split(".").str[0].str.zfill(6)
    )
    staged["tipo_agravo"] = tipo_agravo

    if "CS_SEXO" in result.columns:
        sexo_blank = _blank_mask(result["CS_SEXO"])
        sexo_val = result["CS_SEXO"].astype(str).str.strip().str.upper().str[:1]
        staged["sexo"] = sexo_val.where(~sexo_blank, None)
    else:
        staged["sexo"] = None

    if "NU_IDADE_N" in result.columns:
        staged["idade_anos"] = result["NU_IDADE_N"].apply(_decode_idade_sinan)
    else:
        staged["idade_anos"] = None

    # Per-agravo column branch. Live-verified ownership (inverted from the
    # pre-research assumption): the GRAV_* family and CLASSI_FIN belong to
    # dengue/chikungunya (GRAV_* structurally gated to CLASSI_FIN=12,
    # "Dengue grave"); TP_ACIDENT/TRA_CLASSI belong to animais peçonhentos.
    # CLASSI_FIN is physically absent from ANIM's source frame, not merely
    # null there — do not decode any of these codes to labels here (raw
    # code storage, decode lives in a backend constants module),
    # and never map TRA_CLASSI values into classi_fin — they are different
    # domains (confirm/discard classification vs. severity scale).
    if tipo_agravo in DENG_CHIK_AGRAVOS:
        if "CLASSI_FIN" in result.columns:
            staged["classi_fin"] = _raw_code_to_int(result["CLASSI_FIN"])
        else:
            logger.warning(
                "stage_sinan: CLASSI_FIN column absent for %s — classi_fin left None",
                tipo_agravo,
            )
            staged["classi_fin"] = None

        present_grav_cols = [c for c in GRAV_COLUMNS if c in result.columns]
        if present_grav_cols:
            grav_frame = (
                result[present_grav_cols].astype(str).apply(lambda s: s.str.strip())
            )
            staged["gravidade_grave"] = grav_frame.eq("1").any(axis=1)
        else:
            logger.warning(
                "stage_sinan: 0 of %d GRAV_* columns found for %s — "
                "gravidade_grave left None",
                len(GRAV_COLUMNS),
                tipo_agravo,
            )
            staged["gravidade_grave"] = None

        staged["tra_classi"] = None
        staged["tp_acidente"] = None
    elif tipo_agravo == "ANIM":
        staged["classi_fin"] = None
        staged["gravidade_grave"] = None

        if "TRA_CLASSI" in result.columns:
            staged["tra_classi"] = _raw_code_to_int(result["TRA_CLASSI"])
        else:
            logger.warning(
                "stage_sinan: TRA_CLASSI column absent for ANIM — tra_classi left None"
            )
            staged["tra_classi"] = None

        if "TP_ACIDENT" in result.columns:
            staged["tp_acidente"] = _raw_code_to_int(result["TP_ACIDENT"])
        else:
            logger.warning(
                "stage_sinan: TP_ACIDENT column absent for ANIM — tp_acidente left None"
            )
            staged["tp_acidente"] = None
    else:
        raise ValueError(
            f"stage_sinan: unrecognised tipo_agravo {tipo_agravo!r} — "
            "must be one of 'DENG', 'CHIK', 'ANIM'"
        )

    staged["numero_notificacao"] = _build_numero_notificacao(
        result, staged, tipo_agravo, ordinal_offsets
    )

    return staged[STAGED_COLUMNS]
