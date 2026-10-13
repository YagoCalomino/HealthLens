"""Unit tests for the SINAN mart loader (etl/mart/notificacoes_loader.py).

load_notificacoes is tested against a unittest.mock.MagicMock connection so
the upsert SQL/params can be asserted without a live Postgres.

Run with:
    cd backend && SAMPLE_MODE=true pytest tests/test_etl_mart_notificacoes_loader.py -v
"""

import math
from datetime import date
from unittest.mock import MagicMock, patch

import pandas as pd

from etl.mart.dim_lookup import DimCache
from etl.mart.notificacoes_loader import load_notificacoes


def _make_cache() -> DimCache:
    cache = DimCache()
    cache.tempo = {(2023, 3): 1}
    # Two distinct dim_local entries — one for the residence code used by
    # _staged_sinan_df, one for a notifying-unit code that must NEVER be
    # the one resolved (residence-attribution test).
    cache.local = {"355030": 500, "330455": 900}
    cache.agravo = {"DENG": 10, "CHIK": 11, "ANIM": 12}
    cache.faixa_etaria = {"0_4": 1, "35_44": 5, "ignorada": 99}
    cache.populacao = {("355030", 2023): 12_396_372}
    return cache


def _staged_sinan_df(
    n_rows: int = 3,
    tipo_agravo: str = "DENG",
    municipio_residencia: str = "355030",
) -> pd.DataFrame:
    rows = []
    for i in range(n_rows):
        rows.append(
            {
                "numero_notificacao": f"2023{tipo_agravo}{i:06d}-0",
                "tipo_agravo": tipo_agravo,
                "ano": 2023,
                "mes": 3,
                "municipio_residencia": municipio_residencia,
                "sexo": "F",
                "idade_anos": 40,
                "classi_fin": 10 if tipo_agravo != "ANIM" else None,
                "gravidade_grave": False if tipo_agravo != "ANIM" else None,
                "tra_classi": None if tipo_agravo != "ANIM" else 1,
                "tp_acidente": None if tipo_agravo != "ANIM" else 3,
                "dt_notific": date(2023, 3, 15),
            }
        )
    return pd.DataFrame(rows)


# Column order matches the 14-column _UPSERT_SQL parameter tuple.
_TIPO_AGRAVO_IDX = 4
_NUMERO_NOTIFICACAO_IDX = 5
_NOTIFICACOES_IDX = 6
_TAXA_IDX = 7
_SEXO_IDX = 8
_IDADE_IDX = 9
_CLASSI_FIN_IDX = 10
_GRAVIDADE_GRAVE_IDX = 11
_TRA_CLASSI_IDX = 12
_TP_ACIDENTE_IDX = 13
_DT_NOTIFIC_IDX = 14
_DIM_LOCAL_IDX = 1


@patch("etl.mart.notificacoes_loader.psycopg2.extras.execute_values")
def test_load_notificacoes_upserts_all_staged_rows(mock_execute_values):
    staged = _staged_sinan_df(3)
    cache = _make_cache()
    conn = MagicMock()

    result = load_notificacoes(staged, cache, conn)

    assert result == 3
    mock_execute_values.assert_called_once()
    call_args = mock_execute_values.call_args
    sql = call_args[0][1]
    params = call_args[0][2]
    assert "ON CONFLICT" in sql
    assert len(params) == 3


def test_upsert_sql_contains_on_conflict_composite_key():
    from etl.mart.notificacoes_loader import _UPSERT_SQL

    normalized = " ".join(_UPSERT_SQL.split())
    assert "ON CONFLICT (numero_notificacao, tipo_agravo) DO UPDATE SET" in normalized


@patch("etl.mart.notificacoes_loader.psycopg2.extras.execute_values")
def test_load_notificacoes_skips_unresolvable_local(mock_execute_values):
    staged = _staged_sinan_df(2)
    staged.loc[0, "municipio_residencia"] = "999999"  # not in cache.local
    cache = _make_cache()
    conn = MagicMock()

    result = load_notificacoes(staged, cache, conn)

    assert result == 1
    call_args = mock_execute_values.call_args
    params = call_args[0][2]
    assert len(params) == 1


@patch("etl.mart.notificacoes_loader.psycopg2.extras.execute_values")
def test_load_notificacoes_skips_unresolvable_agravo(mock_execute_values):
    staged = _staged_sinan_df(2)
    staged.loc[0, "tipo_agravo"] = "ZIKA"  # not in cache.agravo
    cache = _make_cache()
    conn = MagicMock()

    result = load_notificacoes(staged, cache, conn)

    assert result == 1
    call_args = mock_execute_values.call_args
    params = call_args[0][2]
    assert len(params) == 1


@patch("etl.mart.notificacoes_loader.psycopg2.extras.execute_values")
def test_load_notificacoes_local_and_agravo_skip_counts_are_separate(
    mock_execute_values,
):
    staged = _staged_sinan_df(3)
    staged.loc[0, "municipio_residencia"] = "999999"
    staged.loc[1, "tipo_agravo"] = "ZIKA"
    cache = _make_cache()
    conn = MagicMock()

    result = load_notificacoes(staged, cache, conn)

    # Row 0 skipped for local, row 1 skipped for agravo, row 2 upserted.
    assert result == 1


@patch("etl.mart.notificacoes_loader.psycopg2.extras.execute_values")
def test_dim_local_id_resolved_from_residence_not_notifying_unit(mock_execute_values):
    staged = _staged_sinan_df(1, municipio_residencia="355030")
    cache = _make_cache()
    conn = MagicMock()

    load_notificacoes(staged, cache, conn)

    call_args = mock_execute_values.call_args
    params = call_args[0][2]
    # cache.local["355030"] = 500 (residence); cache.local["330455"] = 900
    # (a distinct notifying-unit code also present in the cache) must never
    # be the one resolved.
    assert params[0][_DIM_LOCAL_IDX] == 500
    assert params[0][_DIM_LOCAL_IDX] != 900


@patch("etl.mart.notificacoes_loader.psycopg2.extras.execute_values")
def test_taxa_por_100k_computed_from_known_population(mock_execute_values):
    staged = _staged_sinan_df(1)
    cache = _make_cache()
    conn = MagicMock()

    load_notificacoes(staged, cache, conn)

    call_args = mock_execute_values.call_args
    params = call_args[0][2]
    expected = 1.0 / 12_396_372 * 100_000
    assert params[0][_TAXA_IDX] == expected


@patch("etl.mart.notificacoes_loader.psycopg2.extras.execute_values")
def test_taxa_por_100k_is_none_without_population(mock_execute_values):
    staged = _staged_sinan_df(1)
    staged.loc[0, "ano"] = 1999  # no population seeded for this (muni, ano)
    cache = _make_cache()
    conn = MagicMock()

    load_notificacoes(staged, cache, conn)

    call_args = mock_execute_values.call_args
    params = call_args[0][2]
    assert params[0][_TAXA_IDX] is None


@patch("etl.mart.notificacoes_loader.psycopg2.extras.execute_values")
def test_notificacoes_is_always_the_literal_one(mock_execute_values):
    staged = _staged_sinan_df(2)
    cache = _make_cache()
    conn = MagicMock()

    load_notificacoes(staged, cache, conn)

    call_args = mock_execute_values.call_args
    params = call_args[0][2]
    for tup in params:
        assert tup[_NOTIFICACOES_IDX] == 1


@patch("etl.mart.notificacoes_loader.psycopg2.extras.execute_values")
def test_anim_row_sends_none_for_classi_fin_and_gravidade_grave(mock_execute_values):
    staged = _staged_sinan_df(1, tipo_agravo="ANIM")
    cache = _make_cache()
    conn = MagicMock()

    load_notificacoes(staged, cache, conn)

    call_args = mock_execute_values.call_args
    params = call_args[0][2]
    assert params[0][_CLASSI_FIN_IDX] is None
    assert params[0][_GRAVIDADE_GRAVE_IDX] is None
    # ANIM does carry tra_classi/tp_acidente
    assert params[0][_TRA_CLASSI_IDX] == 1
    assert params[0][_TP_ACIDENTE_IDX] == 3


@patch("etl.mart.notificacoes_loader.psycopg2.extras.execute_values")
def test_deng_row_sends_none_for_tra_classi_and_tp_acidente(mock_execute_values):
    staged = _staged_sinan_df(1, tipo_agravo="DENG")
    cache = _make_cache()
    conn = MagicMock()

    load_notificacoes(staged, cache, conn)

    call_args = mock_execute_values.call_args
    params = call_args[0][2]
    assert params[0][_TRA_CLASSI_IDX] is None
    assert params[0][_TP_ACIDENTE_IDX] is None
    assert params[0][_CLASSI_FIN_IDX] == 10


@patch("etl.mart.notificacoes_loader.psycopg2.extras.execute_values")
def test_nan_fields_are_sent_as_none_never_float_nan_or_string(mock_execute_values):
    staged = _staged_sinan_df(1, tipo_agravo="DENG")
    staged.loc[0, "sexo"] = float("nan")
    staged.loc[0, "idade_anos"] = float("nan")
    staged.loc[0, "classi_fin"] = float("nan")
    cache = _make_cache()
    conn = MagicMock()

    load_notificacoes(staged, cache, conn)

    call_args = mock_execute_values.call_args
    params = call_args[0][2]
    tup = params[0]
    assert tup[_SEXO_IDX] is None
    assert tup[_IDADE_IDX] is None
    assert tup[_CLASSI_FIN_IDX] is None
    for value in tup:
        assert not (isinstance(value, float) and math.isnan(value))
        assert value != "nan"


@patch("etl.mart.notificacoes_loader.psycopg2.extras.execute_values")
def test_batch_of_more_than_1000_rows_produces_multiple_execute_values_calls(
    mock_execute_values,
):
    staged = _staged_sinan_df(1500)
    cache = _make_cache()
    conn = MagicMock()

    result = load_notificacoes(staged, cache, conn)

    assert result == 1500
    assert mock_execute_values.call_count == 2


# --- dt_notific ---


@patch("etl.mart.notificacoes_loader.psycopg2.extras.execute_values")
def test_upsert_tuple_length_grew_by_exactly_one_for_dt_notific(mock_execute_values):
    staged = _staged_sinan_df(1)
    cache = _make_cache()
    conn = MagicMock()

    load_notificacoes(staged, cache, conn)

    call_args = mock_execute_values.call_args
    params = call_args[0][2]
    assert len(params[0]) == 15


@patch("etl.mart.notificacoes_loader.psycopg2.extras.execute_values")
def test_dt_notific_sent_as_staged_date(mock_execute_values):
    staged = _staged_sinan_df(1)
    cache = _make_cache()
    conn = MagicMock()

    load_notificacoes(staged, cache, conn)

    call_args = mock_execute_values.call_args
    params = call_args[0][2]
    assert params[0][_DT_NOTIFIC_IDX] == date(2023, 3, 15)


@patch("etl.mart.notificacoes_loader.psycopg2.extras.execute_values")
def test_dt_notific_missing_value_sent_as_none(mock_execute_values):
    staged = _staged_sinan_df(1)
    staged.loc[0, "dt_notific"] = float("nan")
    cache = _make_cache()
    conn = MagicMock()

    load_notificacoes(staged, cache, conn)

    call_args = mock_execute_values.call_args
    params = call_args[0][2]
    assert params[0][_DT_NOTIFIC_IDX] is None


def test_upsert_sql_dt_notific_in_insert_and_conflict_update():
    from etl.mart.notificacoes_loader import _UPSERT_SQL

    normalized = " ".join(_UPSERT_SQL.split())
    assert "dt_notific" in normalized.split("VALUES")[0]
    assert "dt_notific = EXCLUDED.dt_notific" in normalized
