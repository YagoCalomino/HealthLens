"""Unit tests for etl.staging.sinan_staging (SINAN raw-to-staging transform).

Pure pandas fixtures, no DB / network access required. Run with:
    cd backend && SAMPLE_MODE=true pytest tests/test_etl_staging_sinan.py -v
"""

from datetime import date
from unittest.mock import patch

import pandas as pd
import pytest

from etl.staging.sinan_staging import STAGED_COLUMNS, stage_sinan


def _make_deng_frame(**overrides) -> pd.DataFrame:
    """Build a minimal raw DENG fixture. ID_MUNICIP deliberately differs
    from ID_MN_RESI so residence-attribution assertions are meaningful."""
    base = {
        "TP_NOT": ["2", "2"],
        "ID_AGRAVO": ["A90", "A90"],
        "DT_NOTIFIC": ["15032023", "20042023"],
        "NU_ANO": ["2023", "2023"],
        "SG_UF_NOT": ["35", "35"],
        "ID_MUNICIP": ["355030", "355030"],
        "SG_UF": ["35", "35"],
        "ID_MN_RESI": ["354990", "354990"],
        "CS_SEXO": ["F", "M"],
        "NU_IDADE_N": ["4025", "4040"],
        "CLASSI_FIN": ["10", "12"],
        "GRAV_PULSO": ["2", "1"],
        "GRAV_CONV": ["2", "2"],
        "GRAV_ENCH": ["2", "2"],
        "GRAV_INSUF": ["2", "2"],
        "GRAV_TAQUI": ["2", "2"],
        "GRAV_EXTRE": ["2", "2"],
        "GRAV_HIPOT": ["2", "2"],
        "GRAV_HEMAT": ["2", "2"],
        "GRAV_MELEN": ["2", "2"],
        "GRAV_METRO": ["2", "2"],
        "GRAV_SANG": ["2", "2"],
        "GRAV_AST": ["2", "2"],
        "GRAV_MIOC": ["2", "2"],
        "GRAV_CONSC": ["2", "2"],
        "GRAV_ORGAO": ["2", "2"],
        "TRA_CLASSI": [None, None],
        "TP_ACIDENT": [None, None],
        "NU_NOTIFIC": ["1234567", "7654321"],
    }
    base.update(overrides)
    return pd.DataFrame(base)


def _make_anim_frame(**overrides) -> pd.DataFrame:
    """Build a minimal raw ANIM fixture — no CLASSI_FIN/GRAV_* columns at
    all (physically absent, not merely null)."""
    base = {
        "TP_NOT": ["2", "2"],
        "ID_AGRAVO": ["A82", "A82"],
        "DT_NOTIFIC": ["10012023", "05022023"],
        "NU_ANO": ["2023", "2023"],
        "SG_UF_NOT": ["35", "35"],
        "ID_MUNICIP": ["355030", "355030"],
        "SG_UF": ["35", "35"],
        "ID_MN_RESI": ["354990", "354990"],
        "CS_SEXO": ["M", "F"],
        "NU_IDADE_N": ["4030", "1015"],
        "TRA_CLASSI": ["1", "3"],
        "TP_ACIDENT": ["3", "1"],
        "NU_NOTIFIC": ["9988776", "6677889"],
    }
    base.update(overrides)
    return pd.DataFrame(base)


# --- Basic shape / column contract ---


def test_stage_sinan_returns_staged_columns_in_order():
    staged = stage_sinan(_make_deng_frame(), "DENG")
    assert list(staged.columns) == STAGED_COLUMNS


def test_stage_sinan_empty_frame_returns_empty_with_full_columns():
    staged = stage_sinan(pd.DataFrame(), "DENG")
    assert list(staged.columns) == STAGED_COLUMNS
    assert len(staged) == 0


def test_stage_sinan_missing_dt_notific_returns_empty_with_full_columns():
    df = _make_deng_frame().drop(columns=["DT_NOTIFIC"])
    staged = stage_sinan(df, "DENG")
    assert list(staged.columns) == STAGED_COLUMNS
    assert len(staged) == 0


def test_stage_sinan_missing_id_mn_resi_returns_empty_with_full_columns():
    df = _make_deng_frame().drop(columns=["ID_MN_RESI"])
    staged = stage_sinan(df, "DENG")
    assert list(staged.columns) == STAGED_COLUMNS
    assert len(staged) == 0


# --- Drop-and-count validation ---


def test_stage_sinan_drops_rows_with_null_id_mn_resi(caplog):
    df = _make_deng_frame()
    df.loc[0, "ID_MN_RESI"] = None
    with caplog.at_level("INFO"):
        staged = stage_sinan(df, "DENG")
    assert len(staged) == 1
    assert "dropped 1 rows" in caplog.text


def test_stage_sinan_drops_rows_with_blank_id_mn_resi():
    df = _make_deng_frame()
    df.loc[0, "ID_MN_RESI"] = ""
    staged = stage_sinan(df, "DENG")
    assert len(staged) == 1


def test_stage_sinan_drops_rows_with_unparseable_dt_notific(caplog):
    df = _make_deng_frame()
    df.loc[0, "DT_NOTIFIC"] = "not-a-date"
    with caplog.at_level("INFO"):
        staged = stage_sinan(df, "DENG")
    assert len(staged) == 1
    assert "dropped 1 rows" in caplog.text


# --- Residence attribution ---


def test_stage_sinan_uses_id_mn_resi_not_id_municip():
    df = _make_deng_frame(
        ID_MUNICIP=["355030", "355030"], ID_MN_RESI=["354990", "354990"]
    )
    staged = stage_sinan(df, "DENG")
    assert (staged["municipio_residencia"] == "354990").all()
    assert (staged["municipio_residencia"] != "355030").all()


def test_stage_sinan_municipio_residencia_zero_padded_to_6():
    df = _make_deng_frame(ID_MN_RESI=["9990", "9990"])
    staged = stage_sinan(df, "DENG")
    assert (staged["municipio_residencia"] == "009990").all()


# --- ano/mes derivation ---


def test_stage_sinan_ano_mes_from_ddmmyyyy_string():
    df = _make_deng_frame(DT_NOTIFIC=["15032023", "20122022"])
    staged = stage_sinan(df, "DENG")
    assert staged.iloc[0]["ano"] == 2023
    assert staged.iloc[0]["mes"] == 3
    assert staged.iloc[1]["ano"] == 2022
    assert staged.iloc[1]["mes"] == 12


def test_stage_sinan_ano_mes_from_yyyymmdd_string():
    """Regression test for a rehearsal finding: real ANIM 2023
    DT_NOTIFIC values are YYYYMMDD (e.g. "20230101"), not DDMMYYYY. A batch
    of these must not be silently dropped by a hardcoded DDMMYYYY parse."""
    df = _make_anim_frame(DT_NOTIFIC=["20230101", "20230630"])
    staged = stage_sinan(df, "ANIM")
    assert len(staged) == 2
    assert staged.iloc[0]["ano"] == 2023
    assert staged.iloc[0]["mes"] == 1
    assert staged.iloc[1]["ano"] == 2023
    assert staged.iloc[1]["mes"] == 6


def test_stage_sinan_ano_mes_from_datetime64_column():
    df = _make_deng_frame()
    df["DT_NOTIFIC"] = pd.to_datetime(["2023-03-15", "2023-04-20"])
    staged = stage_sinan(df, "DENG")
    assert staged.iloc[0]["ano"] == 2023
    assert staged.iloc[0]["mes"] == 3
    assert staged.iloc[1]["mes"] == 4


# --- dt_notific ---


def test_stage_sinan_dt_notific_in_staged_columns():
    assert "dt_notific" in STAGED_COLUMNS


def test_stage_sinan_dt_notific_from_ddmmyyyy_string():
    df = _make_deng_frame(DT_NOTIFIC=["15012023", "20122022"])
    staged = stage_sinan(df, "DENG")
    assert staged.iloc[0]["dt_notific"] == date(2023, 1, 15)
    assert staged.iloc[1]["dt_notific"] == date(2022, 12, 20)


def test_stage_sinan_dt_notific_from_yyyymmdd_string_matches_ano_mes():
    df = _make_anim_frame(DT_NOTIFIC=["20230101", "20230630"])
    staged = stage_sinan(df, "ANIM")
    assert staged.iloc[0]["dt_notific"] == date(2023, 1, 1)
    assert staged.iloc[0]["ano"] == staged.iloc[0]["dt_notific"].year
    assert staged.iloc[0]["mes"] == staged.iloc[0]["dt_notific"].month
    assert staged.iloc[1]["dt_notific"] == date(2023, 6, 30)


def test_stage_sinan_calls_parse_dt_notific_exactly_once():
    df = _make_deng_frame()
    with patch(
        "etl.staging.sinan_staging._parse_dt_notific",
        wraps=__import__(
            "etl.staging.sinan_staging", fromlist=["_parse_dt_notific"]
        )._parse_dt_notific,
    ) as mock_parse:
        stage_sinan(df, "DENG")
    assert mock_parse.call_count == 1


# --- numero_notificacao ---


def test_stage_sinan_numero_notificacao_unique():
    df = _make_deng_frame()
    staged = stage_sinan(df, "DENG")
    assert staged["numero_notificacao"].is_unique
    assert staged["numero_notificacao"].str.len().max() <= 40


def test_stage_sinan_numero_notificacao_deterministic_on_rerun():
    df = _make_deng_frame()
    staged1 = stage_sinan(df, "DENG")
    staged2 = stage_sinan(df, "DENG")
    assert (
        staged1["numero_notificacao"].reset_index(drop=True)
        == staged2["numero_notificacao"].reset_index(drop=True)
    ).all()


def test_stage_sinan_chunked_keys_do_not_collide_across_chunks():
    # Public SINAN files carry no NU_NOTIFIC, so every row falls back to
    # ano+mes+municipio and only the ordinal tells same-month, same-municipio
    # notifications apart. Chunks staged independently each restart the
    # ordinal at 0, and the upsert silently overwrote ~32% of DENG 2025.
    df = pd.concat([_make_deng_frame()] * 5, ignore_index=True).drop(
        columns=["NU_NOTIFIC"]
    )
    whole = stage_sinan(df, "DENG")["numero_notificacao"].tolist()

    offsets: dict[str, int] = {}
    chunked = []
    for start in range(0, len(df), 3):
        staged = stage_sinan(
            df.iloc[start : start + 3], "DENG", ordinal_offsets=offsets
        )
        chunked.extend(staged["numero_notificacao"])

    assert len(set(chunked)) == len(df)
    assert chunked == whole


def test_stage_sinan_numero_notificacao_falls_back_when_nu_notific_absent():
    df = _make_deng_frame().drop(columns=["NU_NOTIFIC"])
    staged = stage_sinan(df, "DENG")
    assert staged["numero_notificacao"].is_unique
    assert staged["numero_notificacao"].notna().all()


def test_stage_sinan_numero_notificacao_falls_back_when_nu_notific_blank():
    df = _make_deng_frame(NU_NOTIFIC=["", "None"])
    staged = stage_sinan(df, "DENG")
    assert staged["numero_notificacao"].is_unique
    assert staged["numero_notificacao"].notna().all()


# --- idade_anos decoding ---


def test_stage_sinan_idade_anos_decodes_4000_series_to_years():
    df = _make_deng_frame(NU_IDADE_N=["4025", "4001"])
    staged = stage_sinan(df, "DENG")
    assert staged.iloc[0]["idade_anos"] == 25
    assert staged.iloc[1]["idade_anos"] == 1


def test_stage_sinan_idade_anos_sub_4000_codes_to_zero():
    df = _make_deng_frame(NU_IDADE_N=["3011", "1005"])
    staged = stage_sinan(df, "DENG")
    assert staged.iloc[0]["idade_anos"] == 0
    assert staged.iloc[1]["idade_anos"] == 0


def test_stage_sinan_idade_anos_unparseable_or_above_120_is_none():
    df = _make_deng_frame(NU_IDADE_N=["not-a-code", "4200"])
    staged = stage_sinan(df, "DENG")
    assert staged.iloc[0]["idade_anos"] is None
    assert staged.iloc[1]["idade_anos"] is None


# --- sexo ---


def test_stage_sinan_sexo_single_uppercase_char():
    df = _make_deng_frame(CS_SEXO=["f", "M"])
    staged = stage_sinan(df, "DENG")
    assert staged.iloc[0]["sexo"] == "F"
    assert staged.iloc[1]["sexo"] == "M"


def test_stage_sinan_sexo_blank_and_literal_none_string_both_become_none():
    df = _make_deng_frame(CS_SEXO=["", "None"])
    staged = stage_sinan(df, "DENG")
    assert staged.iloc[0]["sexo"] is None
    assert staged.iloc[1]["sexo"] is None


# --- Per-agravo column branch ---


def test_stage_sinan_deng_classi_fin_holds_raw_code():
    df = _make_deng_frame(CLASSI_FIN=["10", "12"])
    staged = stage_sinan(df, "DENG")
    assert staged.iloc[0]["classi_fin"] == 10
    assert staged.iloc[1]["classi_fin"] == 12


def test_stage_sinan_chik_classi_fin_holds_raw_code():
    df = _make_deng_frame(CLASSI_FIN=["13", "5"])
    staged = stage_sinan(df, "CHIK")
    assert staged.iloc[0]["classi_fin"] == 13
    assert staged.iloc[1]["classi_fin"] == 5


def test_stage_sinan_classi_fin_empty_string_becomes_none():
    df = _make_deng_frame(CLASSI_FIN=["", "10"])
    staged = stage_sinan(df, "DENG")
    assert staged.iloc[0]["classi_fin"] is None
    assert staged.iloc[1]["classi_fin"] == 10


def test_stage_sinan_classi_fin_literal_none_string_becomes_none():
    df = _make_deng_frame(CLASSI_FIN=["None", "10"])
    staged = stage_sinan(df, "DENG")
    assert staged.iloc[0]["classi_fin"] is None
    assert staged.iloc[1]["classi_fin"] == 10


def test_stage_sinan_deng_chik_tra_classi_tp_acidente_always_none():
    df = _make_deng_frame()
    staged = stage_sinan(df, "DENG")
    assert staged["tra_classi"].isna().all()
    assert staged["tp_acidente"].isna().all()


def test_stage_sinan_gravidade_grave_true_when_any_grav_col_is_1():
    df = _make_deng_frame()
    df.loc[0, "GRAV_PULSO"] = "1"
    df.loc[1, "GRAV_PULSO"] = "2"
    staged = stage_sinan(df, "DENG")
    assert staged.iloc[0]["gravidade_grave"] == True  # noqa: E712
    assert staged.iloc[1]["gravidade_grave"] == False  # noqa: E712


def test_stage_sinan_gravidade_grave_false_when_no_grav_col_is_1():
    df = _make_deng_frame()
    for col in [c for c in df.columns if c.startswith("GRAV_")]:
        df[col] = "2"
    staged = stage_sinan(df, "DENG")
    assert (staged["gravidade_grave"] == False).all()  # noqa: E712


def test_stage_sinan_deng_frame_with_zero_grav_columns_yields_none_and_warns(caplog):
    df = _make_deng_frame().drop(
        columns=[c for c in _make_deng_frame().columns if c.startswith("GRAV_")]
    )
    with caplog.at_level("WARNING"):
        staged = stage_sinan(df, "DENG")
    assert staged["gravidade_grave"].isna().all()
    assert "GRAV_" in caplog.text


def test_stage_sinan_anim_classi_fin_and_gravidade_grave_none():
    df = _make_anim_frame()
    staged = stage_sinan(df, "ANIM")
    assert staged["classi_fin"].isna().all()
    assert staged["gravidade_grave"].isna().all()


def test_stage_sinan_anim_tra_classi_and_tp_acidente_hold_raw_codes():
    df = _make_anim_frame(TRA_CLASSI=["1", "3"], TP_ACIDENT=["3", "1"])
    staged = stage_sinan(df, "ANIM")
    assert staged.iloc[0]["tra_classi"] == 1
    assert staged.iloc[0]["tp_acidente"] == 3
    assert staged.iloc[1]["tra_classi"] == 3
    assert staged.iloc[1]["tp_acidente"] == 1


def test_stage_sinan_anim_missing_tra_classi_yields_none_and_warns(caplog):
    df = _make_anim_frame().drop(columns=["TRA_CLASSI"])
    with caplog.at_level("WARNING"):
        staged = stage_sinan(df, "ANIM")
    assert staged["tra_classi"].isna().all()
    assert "TRA_CLASSI" in caplog.text


def test_stage_sinan_anim_missing_tp_acidente_yields_none_and_warns(caplog):
    df = _make_anim_frame().drop(columns=["TP_ACIDENT"])
    with caplog.at_level("WARNING"):
        staged = stage_sinan(df, "ANIM")
    assert staged["tp_acidente"].isna().all()
    assert "TP_ACIDENT" in caplog.text


def test_stage_sinan_unrecognised_tipo_agravo_raises_value_error():
    df = _make_deng_frame()
    with pytest.raises(ValueError):
        stage_sinan(df, "ZIKA")
