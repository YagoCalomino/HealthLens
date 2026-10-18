"""Unit tests for ML forecasting runner.

All tests are pure Python — no database required.
Run with:
    cd backend && SAMPLE_MODE=true pytest tests/test_ml_forecasting.py -v
"""

import numpy as np
import pandas as pd
import pytest
from statsforecast import StatsForecast
from statsforecast.models import AutoARIMA, CrostonOptimized
from prophet import Prophet

from ml.run_forecasting import (
    _ANO_REFERENCIA,
    _ANOS_FULL,
    _FORECAST_ANOS,
    select_model_for_series,
)

# ---------------------------------------------------------------------------
# Helpers / fixtures
# ---------------------------------------------------------------------------

_YEARS = list(range(2015, 2024))


def _make_series_df(
    unique_id: str = "350300", y_values: list | None = None
) -> pd.DataFrame:
    """Return a StatsForecast-format DataFrame with 9 annual observations (2015-2023)."""
    if y_values is None:
        y_values = [
            float(10 + i * 2) for i in range(9)
        ]  # 10, 12, 14, ... 26 — all nonzero
    return pd.DataFrame(
        {
            "unique_id": unique_id,
            "ds": pd.to_datetime([f"{y}-12-31" for y in _YEARS]),
            "y": y_values,
        }
    )


def _make_sparse_df(unique_id: str = "350001") -> pd.DataFrame:
    """Return a sparse series DataFrame — only 1 nonzero value (triggers HistoricAverage gate)."""
    y_values = [0.0] * 8 + [5.0]
    return _make_series_df(unique_id=unique_id, y_values=y_values)


# ---------------------------------------------------------------------------
# Reference-year regression guards
# ---------------------------------------------------------------------------


def test_ano_referencia_is_2024():
    """_ANO_REFERENCIA must be 2024.

    This constant is write-only — it is never derived from the data, only
    stamped verbatim onto every forecast_resultados row at write time. It is
    then read back by /forecasts (forecasts.py: .where(mv.c.ano <= ano_referencia))
    to cap the historico array. Reverting it to 2023 would silently hide the
    already-ingested 2024 actuals from API consumers.
    """
    assert _ANO_REFERENCIA == 2024


def test_forecast_window_and_training_range_are_current():
    """The training range and forecast window must stay aligned with the reference year.

    max(_ANOS_FULL) == _ANO_REFERENCIA is the real invariant: the reference-year
    label must always track the training data cutoff. This catches a future data
    extension that bumps one without the other, independent of the literal value
    asserted in test_ano_referencia_is_2024.
    """
    assert _ANOS_FULL == list(range(2015, 2025))
    assert _FORECAST_ANOS == [2025, 2026, 2027]
    assert max(_ANOS_FULL) == _ANO_REFERENCIA


# ---------------------------------------------------------------------------
# Sparse gate routing tests (select_model_for_series)
# ---------------------------------------------------------------------------


def test_sparse_gate_routes_autoarima():
    """select_model_for_series passes non-sparse series (n_nonzero>=5 AND sum>=10) to AutoARIMA."""
    train_y = np.array(
        [12.0, 15.0, 18.0, 14.0, 20.0, 16.0, 19.0]
    )  # 7 obs, all nonzero, sum=114
    model, name = select_model_for_series(train_y)
    assert name == "AutoARIMA"


def test_sparse_gate_routes_croston():
    """select_model_for_series falls back to CrostonOptimized when n_nonzero<5 but n_nonzero>=2."""
    train_y = np.array([5.0, 0.0, 0.0, 0.0, 0.0, 3.0, 0.0])  # 2 nonzero, sum=8 (sum<10)
    model, name = select_model_for_series(train_y)
    assert name == "CrostonOptimized"


def test_sparse_gate_routes_historic_average():
    """select_model_for_series falls back to HistoricAverage when n_nonzero<2."""
    train_y = np.array([0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 5.0])  # 1 nonzero only
    model, name = select_model_for_series(train_y)
    assert name == "HistoricAverage"


# ---------------------------------------------------------------------------
# StatsForecast backtest and ds offset tests
# ---------------------------------------------------------------------------


def test_backtest_years():
    """cross_validation with h=2, n_windows=1 on a 9-obs series validates on years 2022 and 2023."""
    df_full = _make_series_df()
    sf = StatsForecast(models=[AutoARIMA(season_length=1)], freq="YE", n_jobs=1)
    cv = sf.cross_validation(df=df_full, h=2, n_windows=1)
    validation_years = sorted(cv["ds"].dt.year.tolist())
    assert 2022 in validation_years
    assert 2023 in validation_years


def test_ds_year_offset():
    """sf.forecast with ds=YYYY-12-31 and freq='YE' produces forecast years 2024, 2025, 2026 for h=3."""
    df_full = _make_series_df()
    sf = StatsForecast(models=[AutoARIMA(season_length=1)], freq="YE", n_jobs=1)
    fc = sf.forecast(df=df_full, h=3, level=[80, 95])
    forecast_years = fc["ds"].dt.year.tolist()
    assert forecast_years == [2024, 2025, 2026], (
        f"Expected [2024, 2025, 2026] but got {forecast_years} — "
        "check ds=YYYY-12-31 + freq='YE' alignment"
    )


# ---------------------------------------------------------------------------
# ConformalIntervals requirement test
# ---------------------------------------------------------------------------


def test_conformal_intervals():
    """CrostonOptimized CI request without ConformalIntervals raises an error.

    This is expected behavior: fallback models require prediction_intervals=ConformalIntervals()
    when requesting confidence bands via level=[80,95].

    Note: statsforecast 2.0.3 raises bare Exception (not ValueError) with message
    "You must pass `prediction_intervals` to compute them." — captured as Exception.
    """
    df_sparse = _make_sparse_df()
    sf = StatsForecast([CrostonOptimized()], freq="YE", n_jobs=1)
    with pytest.raises(Exception, match="prediction_intervals"):
        sf.forecast(df=df_sparse, h=3, level=[80, 95])


# ---------------------------------------------------------------------------
# Prophet tests
# ---------------------------------------------------------------------------


def test_prophet_predict():
    """Prophet fit + predict returns DataFrame with columns yhat, yhat_lower, yhat_upper."""
    df_train = _make_series_df()[["ds", "y"]].copy()
    m = Prophet(
        yearly_seasonality=False,
        weekly_seasonality=False,
        daily_seasonality=False,
        interval_width=0.80,
    )
    m.fit(df_train)
    future = pd.DataFrame(
        {"ds": pd.to_datetime(["2024-12-31", "2025-12-31", "2026-12-31"])}
    )
    forecast = m.predict(future)
    assert "yhat" in forecast.columns
    assert "yhat_lower" in forecast.columns
    assert "yhat_upper" in forecast.columns


def test_prophet_dual_ci():
    """Two Prophet fits with interval_width=0.80 and 0.95 produce different yhat_lower values.

    Prophet's interval_width is a constructor parameter: a single fit produces only one
    CI band. Two separate fits are required for 80% + 95% CI. This test confirms that
    the two fits produce distinct lower bounds.
    """
    df_train = _make_series_df()[["ds", "y"]].copy()
    future = pd.DataFrame(
        {"ds": pd.to_datetime(["2024-12-31", "2025-12-31", "2026-12-31"])}
    )

    m80 = Prophet(
        yearly_seasonality=False,
        weekly_seasonality=False,
        daily_seasonality=False,
        interval_width=0.80,
    )
    m80.fit(df_train)
    fc80 = m80.predict(future)

    m95 = Prophet(
        yearly_seasonality=False,
        weekly_seasonality=False,
        daily_seasonality=False,
        interval_width=0.95,
    )
    m95.fit(df_train)
    fc95 = m95.predict(future)

    yhat_lower_80 = fc80["yhat_lower"].values
    yhat_lower_95 = fc95["yhat_lower"].values

    assert not np.allclose(yhat_lower_80, yhat_lower_95), (
        "yhat_lower for interval_width=0.80 and 0.95 should differ — "
        "ensure two separate Prophet fits are performed (not one reused)"
    )
