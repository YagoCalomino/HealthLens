"""Unit tests for the SIM mart loader (etl/mart/obitos_loader.py).

load_obitos is tested against a unittest.mock.MagicMock connection so the
upsert SQL/params can be asserted without a live Postgres.

Run with:
    cd backend && SAMPLE_MODE=true pytest tests/test_etl_mart_obitos_loader.py -v
"""

from unittest.mock import MagicMock, patch

import pandas as pd

from etl.mart.dim_lookup import DimCache
from etl.mart.obitos_loader import load_obitos


def _make_cache() -> DimCache:
    cache = DimCache()
    cache.tempo = {(2022, 3): 1}
    cache.local = {"355030": 500}
    cache.causa = {"I219": 2}
    cache.faixa_etaria = {"0_4": 10, "ignorada": 99}
    cache.populacao = {("355030", 2022): 12_396_372}
    return cache


def _staged_sim_df(n_rows: int = 3, raca_cor: str = "1") -> pd.DataFrame:
    rows = []
    for i in range(n_rows):
        rows.append(
            {
                "numero_do": f"DO2022SP{i:06d}",
                "revisao_numero": 0,
                "ano": 2022,
                "mes": 3,
                "causa_basica": "I219",
                "municipio_residencia": "355030",
                "sexo": "1",
                "idade_anos": 60,
                "raca_cor": raca_cor,
            }
        )
    return pd.DataFrame(rows)


@patch("etl.mart.obitos_loader.psycopg2.extras.execute_values")
def test_load_obitos_upserts_all_staged_rows(mock_execute_values):
    staged = _staged_sim_df(3)
    cache = _make_cache()
    conn = MagicMock()

    result = load_obitos(staged, cache, conn)

    assert result == 3
    mock_execute_values.assert_called_once()
    call_args = mock_execute_values.call_args
    sql = call_args[0][1]
    params = call_args[0][2]
    assert "ON CONFLICT" in sql
    assert "DO UPDATE" in sql
    assert len(params) == 3


@patch("etl.mart.obitos_loader.psycopg2.extras.execute_values")
def test_load_obitos_skips_unresolvable_causa(mock_execute_values):
    staged = _staged_sim_df(2)
    staged.loc[0, "causa_basica"] = "Z999"  # not in cache.causa, no prefix match
    cache = _make_cache()
    conn = MagicMock()

    result = load_obitos(staged, cache, conn)

    assert result == 1
    call_args = mock_execute_values.call_args
    params = call_args[0][2]
    assert len(params) == 1


@patch("etl.mart.obitos_loader.psycopg2.extras.execute_values")
def test_load_obitos_skips_unresolvable_local(mock_execute_values):
    staged = _staged_sim_df(2)
    staged.loc[0, "municipio_residencia"] = "999999"  # not in cache.local
    cache = _make_cache()
    conn = MagicMock()

    result = load_obitos(staged, cache, conn)

    assert result == 1
    call_args = mock_execute_values.call_args
    params = call_args[0][2]
    assert len(params) == 1


def test_upsert_sql_contains_raca_cor_insert_and_update():
    """_UPSERT_SQL must add raca_cor to both the INSERT column list and
    the ON CONFLICT DO UPDATE SET clause (revision cycles must
    also refresh raca_cor, not leave it stale)."""
    from etl.mart.obitos_loader import _UPSERT_SQL

    assert "raca_cor" in _UPSERT_SQL
    normalized = " ".join(_UPSERT_SQL.split())
    assert "raca_cor = EXCLUDED.raca_cor" in normalized


@patch("etl.mart.obitos_loader.psycopg2.extras.execute_values")
def test_load_obitos_writes_raca_cor_value(mock_execute_values):
    staged = _staged_sim_df(1, raca_cor="4")
    cache = _make_cache()
    conn = MagicMock()

    load_obitos(staged, cache, conn)

    call_args = mock_execute_values.call_args
    params = call_args[0][2]
    assert params[0][-1] == "4"


@patch("etl.mart.obitos_loader.psycopg2.extras.execute_values")
def test_load_obitos_raca_cor_none_and_nan_become_none(mock_execute_values):
    staged = _staged_sim_df(2)
    staged.loc[0, "raca_cor"] = None
    staged.loc[1, "raca_cor"] = float("nan")
    cache = _make_cache()
    conn = MagicMock()

    load_obitos(staged, cache, conn)

    call_args = mock_execute_values.call_args
    params = call_args[0][2]
    assert params[0][-1] is None
    assert params[1][-1] is None
