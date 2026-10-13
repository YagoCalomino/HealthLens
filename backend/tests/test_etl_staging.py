"""Unit tests for ETL staging transformations.

All tests are pure-Python/pandas — no database required.
Run with:
    cd backend && SAMPLE_MODE=true pytest tests/test_etl_staging.py -v
"""

import pathlib
import pandas as pd

from etl.staging.sim_staging import (
    _decode_idade,
    compute_faixa_etaria_codigo,
    stage_sim,
)
from etl.staging.sih_staging import stage_sih

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_VALID_SIM_ROW = {
    "NUMERODO": "DO2022SP000001",
    "DTOBITO": "20220315",
    "CAUSABAS": "I21",
    "CODMUNRES": "355030",
    "SEXO": "1",
    "IDADE": 460,  # 460 - 400 = 60 years
    "REVISAO": 0,
}

_VALID_SIH_ROW = {
    "N_AIH": "AIH000001",
    "IDENT": "1",
    "DT_INTER": "20220101",
    "DIAG_PRINC": "I21",
    "MUNIC_RES": "355030",
    "SEXO": "1",
    "NASC": "19620101",
    "MORTE": 0,
    "VAL_TOT": 1000.0,
    "QT_DIARIAS": 5,
}

_SIM_REQUIRED_COLS = [
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

_SIH_REQUIRED_COLS = [
    "aih_numero",
    "sp_tipo",
    "ano",
    "mes",
    "causa_basica",
    "municipio_residencia",
    "sexo",
    "idade_anos",
    "obitos_internacao",
    "dias_permanencia",
    "valor_total",
]


# ---------------------------------------------------------------------------
# SIM staging tests
# ---------------------------------------------------------------------------


def test_sim_staging_normalizes_columns():
    """stage_sim maps raw DataSUS SIM columns to canonical staging schema."""
    df = pd.DataFrame([_VALID_SIM_ROW])
    result = stage_sim(df)

    assert len(result) == 1
    row = result.iloc[0]
    assert row["numero_do"] == "DO2022SP000001"
    assert row["ano"] == 2022
    assert row["mes"] == 3
    assert row["causa_basica"] == "I21"
    assert row["municipio_residencia"] == "355030"
    assert row["sexo"] == "1"
    assert row["idade_anos"] == 60
    assert row["revisao_numero"] == 0


def test_sim_staging_ddmmyyyy_day20_misfire_regression():
    """Regression: a real-pysus DDMMYYYY batch whose FIRST row has day-of-death
    20 must not be misclassified as YYYYMMDD.

    Root cause of the SIM date-corruption bug: the prior heuristic sniffed
    only the first non-null DTOBITO row. For a real "20122022" (20 Dec 2022)
    first row, DD+MM concatenates to "2012" — inside the sniff's 2000-2030
    "looks like a year" window — so the ENTIRE batch was misclassified as
    YYYYMMDD. That corrupted every other row: a genuine "31122022" (31 Dec
    2022) death produced ano=3112 instead of 2022 (DD+MM read as the year).

    This fixture omits NUMERODO/REVISAO (real pysus shape, not synthetic
    sample) so numero_do is derived from CONTADOR/CODUF, forcing the same
    code path real DataSUS Parquet takes.
    """
    rows = [
        {
            "DTOBITO": "20122022",  # day=20 — the misfire trigger row, placed first
            "CAUSABAS": "I21",
            "CODMUNRES": "355030",
            "SEXO": "1",
            "IDADE": 460,
            "CONTADOR": 1,
            "CODUF": "35",
        },
        {
            "DTOBITO": "31122022",  # day=31 — would surface as ano=3112 under the old bug
            "CAUSABAS": "J180",
            "CODMUNRES": "355030",
            "SEXO": "2",
            "IDADE": 430,
            "CONTADOR": 2,
            "CODUF": "35",
        },
    ]
    df = pd.DataFrame(rows)
    result = stage_sim(df, uf="SP", ano=2022)

    assert len(result) == 2
    assert list(result["ano"]) == [2022, 2022], (
        "Expected both rows to resolve to year 2022 (DDMMYYYY correctly "
        f"detected); got {list(result['ano'])} — 3112/2012 would indicate "
        "the single-row sniff regression is back"
    )
    assert list(result["mes"]) == [12, 12]


def test_sim_staging_drops_invalid_rows():
    """stage_sim removes rows with null DTOBITO or null CAUSABAS; valid rows survive."""
    rows = [
        _VALID_SIM_ROW,  # valid
        {**_VALID_SIM_ROW, "DTOBITO": None},  # null DTOBITO
        {**_VALID_SIM_ROW, "CAUSABAS": None},  # null CAUSABAS
    ]
    df = pd.DataFrame(rows)
    result = stage_sim(df)

    assert len(result) == 1, f"Expected 1 valid row after filtering, got {len(result)}"


def test_sim_age_decode():
    """_decode_idade converts DataSUS age codes to whole years."""
    # 400-series: subtract 400 to get years
    assert _decode_idade(422) == 22
    assert _decode_idade(460) == 60

    # 300-series: infant months encoding → age 0
    assert _decode_idade(301) == 0

    # 0 / unknown codes → None (may surface as pd.NA in Series context)
    result = _decode_idade(0)
    assert result is None or pd.isna(result)


def test_faixa_etaria_boundaries():
    """compute_faixa_etaria_codigo maps age in years to standard bucket codes."""
    assert compute_faixa_etaria_codigo(None) == "ignorada"
    assert compute_faixa_etaria_codigo(0) == "0_4"
    assert compute_faixa_etaria_codigo(4) == "0_4"
    assert compute_faixa_etaria_codigo(5) == "5_14"
    assert compute_faixa_etaria_codigo(14) == "5_14"
    assert compute_faixa_etaria_codigo(75) == "75_mais"
    assert compute_faixa_etaria_codigo(99) == "75_mais"


def test_sim_staging_raca_cor_raw_codes():
    """stage_sim extracts RACACOR as-is (raw DataSUS code, no decode)."""
    rows = [
        {**_VALID_SIM_ROW, "NUMERODO": "DO1", "RACACOR": "1"},
        {**_VALID_SIM_ROW, "NUMERODO": "DO2", "RACACOR": "4"},
        {**_VALID_SIM_ROW, "NUMERODO": "DO3", "RACACOR": "5"},
    ]
    df = pd.DataFrame(rows)
    result = stage_sim(df)

    assert list(result["raca_cor"]) == ["1", "4", "5"]
    assert list(result.columns)[-1] == "raca_cor"


def test_sim_staging_raca_cor_blank_and_nan_become_none():
    """stage_sim maps blank/whitespace/NaN RACACOR to SQL NULL, never '' or 'nan'."""
    rows = [
        {**_VALID_SIM_ROW, "NUMERODO": "DO1", "RACACOR": ""},
        {**_VALID_SIM_ROW, "NUMERODO": "DO2", "RACACOR": "  "},
        {**_VALID_SIM_ROW, "NUMERODO": "DO3", "RACACOR": None},
    ]
    df = pd.DataFrame(rows)
    result = stage_sim(df)

    assert result["raca_cor"].isna().all()
    assert not (result["raca_cor"] == "").any()
    assert not (result["raca_cor"] == "nan").any()


def test_sim_staging_raca_cor_missing_column_is_safe():
    """stage_sim tolerates SIM frames with no RACACOR column at all (sample data)."""
    df = pd.DataFrame([_VALID_SIM_ROW])
    assert "RACACOR" not in df.columns

    result = stage_sim(df)

    assert "raca_cor" in result.columns
    assert result["raca_cor"].isna().all()
    assert list(result.columns) == [
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


def test_sim_staging_empty_dataframe_includes_raca_cor_column():
    """The DTOBITO-missing empty-DataFrame early return also carries raca_cor."""
    df = pd.DataFrame([{**_VALID_SIM_ROW, "DTOBITO": None}])
    del df["DTOBITO"]
    result = stage_sim(df)

    assert "raca_cor" in result.columns


# ---------------------------------------------------------------------------
# SIH staging tests
# ---------------------------------------------------------------------------


def test_sih_staging_ident_filter():
    """stage_sih retains only IDENT=1 (incident) AIH rows.

    SP_TIPO is deliberately excluded from the fixture: on real pysus 2.2.0
    SIH-RD output it is always null and must never be used as the incident
    discriminator (see module docstring in sih_staging.py).
    """
    rows = [
        {**_VALID_SIH_ROW, "N_AIH": f"AIH{i}", "IDENT": ident}
        for i, ident in enumerate(["1", "5", "5", "1", "5"])
    ]
    df = pd.DataFrame(rows)
    result = stage_sih(df)

    assert len(result) == 2, f"Expected 2 incident rows (IDENT=1), got {len(result)}"
    assert (result["sp_tipo"] == 1).all(), "Non-incident AIH rows survived IDENT filter"


def test_sih_staging_ignores_null_sp_tipo():
    """Regression: SP_TIPO is always null on genuine SIH-RD rows in pysus 2.2.0
    (pysus concatenates the RD and SP groups; SP_TIPO belongs to SP only).
    stage_sih must rely on IDENT, not SP_TIPO, so null/absent SP_TIPO must not
    cause every row to be dropped.
    """
    rows = [{**_VALID_SIH_ROW, "N_AIH": f"AIH{i}", "SP_TIPO": None} for i in range(3)]
    df = pd.DataFrame(rows)
    result = stage_sih(df)

    assert len(result) == 3, (
        f"Expected all 3 incident rows to survive despite null SP_TIPO, got {len(result)}"
    )


def test_sih_staging_ident_filter_cannot_exclude_rejected_aih():
    """Regression: stage_sih is provably blind to SIH record type (RD vs RJ).

    SIH-RJ ("AIH Rejeitada") rows carry IDENT=1 at ~100% just like genuine
    RD ("AIH Reduzida") rows do — the IDENT=1 filter cannot discriminate
    between them. This is intentional: RD isolation is guaranteed upstream,
    in etl.ingestor._fetch_sih_rd, via a filename-prefix ("RD") filter
    applied to the catalog file list before download. If a future refactor
    ever removes that upstream filter, this test documents the resulting
    failure mode — stage_sih will silently accept rejected-AIH rows as if
    they were valid incident hospitalisations.
    """
    rows = [{**_VALID_SIH_ROW, "N_AIH": f"RJ-AIH{i}", "IDENT": "1"} for i in range(4)]
    df = pd.DataFrame(rows)
    result = stage_sih(df)

    assert len(result) == 4, (
        "stage_sih is expected to retain all IDENT=1 rows regardless of "
        "whether they originated from an RD or RJ source file — the "
        "RD/RJ distinction is not made at this layer (see module docstring "
        "in sih_staging.py and etl.ingestor._fetch_sih_rd)"
    )


def test_sih_staging_normalizes_columns():
    """stage_sih maps raw DataSUS SIH columns to the canonical staging schema."""
    df = pd.DataFrame([_VALID_SIH_ROW])
    result = stage_sih(df)

    missing = [col for col in _SIH_REQUIRED_COLS if col not in result.columns]
    assert not missing, f"Output is missing expected columns: {missing}"


# ---------------------------------------------------------------------------
# Integration: actual sample Parquet
# ---------------------------------------------------------------------------


def test_pipeline_sample_mode_staging():
    """stage_sim processes the committed sample Parquet without errors.

    The sample file is tracked in git (data/sample/sim_sample.parquet) so this
    test always has access to real DataSUS-shaped data without requiring a DB.
    """
    # Anchor to repo root so the path resolves regardless of pytest invocation cwd.
    repo_root = pathlib.Path(__file__).resolve().parents[2]
    sample_path = repo_root / "data" / "sample" / "sim_sample.parquet"
    df = pd.read_parquet(sample_path)
    result = stage_sim(df)

    assert len(result) > 0, "stage_sim produced an empty result from sample data"

    missing = [col for col in _SIM_REQUIRED_COLS if col not in result.columns]
    assert not missing, f"Output is missing required columns: {missing}"

    # Mandatory identity fields must have no nulls
    for col in ("numero_do", "ano", "mes"):
        null_count = result[col].isna().sum()
        assert null_count == 0, (
            f"Column '{col}' has {null_count} null values after staging"
        )
