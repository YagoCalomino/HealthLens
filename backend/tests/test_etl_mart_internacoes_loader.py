"""Unit tests for the SIH mart loader (etl/mart/internacoes_loader.py).

_to_int / _to_float are pure functions — no database required.
load_internacoes is tested against a unittest.mock.MagicMock connection so
the upsert SQL/params can be asserted without a live Postgres.

Run with:
    cd backend && SAMPLE_MODE=true pytest tests/test_etl_mart_internacoes_loader.py -v
"""

from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

from etl.mart.dim_lookup import DimCache
from etl.mart.internacoes_loader import _to_float, _to_int, load_internacoes

# ---------------------------------------------------------------------------
# _to_int
# ---------------------------------------------------------------------------


def test_to_int_numeric_string():
    assert _to_int("5") == 5


def test_to_int_numeric_int():
    assert _to_int(5) == 5


def test_to_int_nan_returns_none():
    assert _to_int(float("nan")) is None


def test_to_int_none_returns_none():
    assert _to_int(None) is None


def test_to_int_empty_string_treated_as_nan_by_pandas_isna():
    # pd.isna("") is False for a plain string — verifies the helper does not
    # blow up on empty strings and instead attempts int() conversion or raises.
    # DataSUS staged numeric columns never carry "" (they use NaN), so this
    # documents the actual (non-guarded) behavior for empty string input.
    with pytest.raises(ValueError):
        _to_int("")


# ---------------------------------------------------------------------------
# _to_float
# ---------------------------------------------------------------------------


def test_to_float_numeric():
    assert _to_float(5) == 5.0
    assert _to_float("5.5") == 5.5


def test_to_float_nan_returns_none():
    assert _to_float(float("nan")) is None


def test_to_float_none_returns_none():
    assert _to_float(None) is None


# ---------------------------------------------------------------------------
# load_internacoes — mocked upsert
# ---------------------------------------------------------------------------


def _make_cache() -> DimCache:
    cache = DimCache()
    cache.tempo = {(2022, 1): 1}
    cache.local = {"355030": 500}
    cache.causa = {"I219": 2}
    cache.faixa_etaria = {"0_4": 10, "ignorada": 99}
    cache.populacao = {("355030", 2022): 12_396_372}
    return cache


def _staged_sih_df(n_rows: int = 3) -> pd.DataFrame:
    rows = []
    for i in range(n_rows):
        rows.append(
            {
                "aih_numero": f"AIH{i}",
                "ano": 2022,
                "mes": 1,
                "municipio_residencia": "355030",
                "causa_basica": "I219",
                "idade_anos": 30,
                "obitos_internacao": 0,
                "dias_permanencia": 5,
                "valor_total": 1000.0,
            }
        )
    return pd.DataFrame(rows)


@patch("etl.mart.internacoes_loader.psycopg2.extras.execute_values")
def test_load_internacoes_upserts_all_staged_rows(mock_execute_values):
    staged = _staged_sih_df(3)
    cache = _make_cache()
    conn = MagicMock()

    # cache.get_or_create_tempo_id / assert_no_non_incident_aih hit conn.cursor()
    # too — make cursor() a context manager returning a MagicMock cursor.
    cursor_cm = MagicMock()
    cursor_cm.fetchone.return_value = (0,)
    conn.cursor.return_value.__enter__.return_value = cursor_cm

    result = load_internacoes(staged, cache, conn)

    assert result == 3
    mock_execute_values.assert_called_once()
    call_args = mock_execute_values.call_args
    sql = call_args[0][1]
    params = call_args[0][2]
    assert "ON CONFLICT" in sql
    assert "DO UPDATE" in sql
    assert len(params) == 3


@patch("etl.mart.internacoes_loader.psycopg2.extras.execute_values")
def test_load_internacoes_skips_unresolvable_local(mock_execute_values):
    staged = _staged_sih_df(2)
    staged.loc[0, "municipio_residencia"] = "999999"  # not in cache.local
    cache = _make_cache()
    conn = MagicMock()

    cursor_cm = MagicMock()
    cursor_cm.fetchone.return_value = (0,)
    conn.cursor.return_value.__enter__.return_value = cursor_cm

    result = load_internacoes(staged, cache, conn)

    assert result == 1
    call_args = mock_execute_values.call_args
    params = call_args[0][2]
    assert len(params) == 1
