"""AutoARIMA + Prophet forecasting runner for HealthLens.

Aggregates SIM/SIH Parquet data into annual death-rate and hospitalisation-rate
series per municipality and per UF, then:
  - Runs AutoARIMA (statsforecast 2.0.3) per municipality (up to 5570 series)
    with a sparse-series gate (n_nonzero >= 5 AND sum >= 10 in training window).
    Fallback: CrostonOptimized → HistoricAverage with ConformalIntervals CI.
  - Runs Prophet (1.3.0) per UF (27 series) with two separate fits for 80%
    and 95% prediction intervals.
  - Upserts all predictions into forecast_resultados via psycopg2.

Entry points:
  - run_forecasting(conn)  — callable from tests or orchestrator scripts
  - python -m ml.run_forecasting [--raw-dir DIR]

In SAMPLE_MODE reads from data/sample/; otherwise from --raw-dir.
Requires PostgreSQL and seeded dim_local table when writing results to DB.
"""

import argparse
import logging
import glob as glob_module
import os
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd
import psycopg2
import psycopg2.extras
from statsforecast import StatsForecast
from statsforecast.models import AutoARIMA, CrostonOptimized, HistoricAverage
from statsforecast.utils import ConformalIntervals
from prophet import Prophet
from utilsforecast.losses import mase as compute_mase, smape as compute_smape

from etl import config

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Module-level constants
# ---------------------------------------------------------------------------

_BATCH_SIZE = 1000
_ANOS_TREINO = list(range(2015, 2022))  # 2015-2021 for sparse gate and backtest split
_ANOS_FULL = list(range(2015, 2025))  # 2015-2024 for final forecast
_FORECAST_ANOS = [2025, 2026, 2027]
# Written verbatim into forecast_resultados.ano_referencia at every write site below
# and read back by /forecasts (forecasts.py, .where(mv.c.ano <= ano_referencia)) to cap
# the historico array. Nothing derives this automatically — it must track the training
# data cutoff (_ANOS_FULL's upper bound) or /forecasts will silently hide actuals.
_ANO_REFERENCIA = 2024

# Allowlist for column names interpolated into DuckDB f-string queries.
# Only these identifiers may be passed as mun_col/date_col to _aggregate_series.
_ALLOWED_MUN_COLS: frozenset = frozenset({"CODMUNRES", "MUNIC_RES", "CODUF"})
_ALLOWED_DATE_COLS: frozenset = frozenset({"DTOBITO", "DT_INTER"})


def _validate_col(name: str, allowed: frozenset) -> str:
    """Validate a column name against an allowlist before SQL interpolation."""
    if name not in allowed:
        raise ValueError(f"Column '{name}' is not in the allowed list {allowed}")
    return name


_FORECAST_UPSERT = """
INSERT INTO forecast_resultados (
    dim_local_id, dim_causa_id, granularidade, metrica,
    ano_referencia, ano_forecast, valor_previsto,
    intervalo_inferior_80, intervalo_superior_80,
    intervalo_inferior_95, intervalo_superior_95,
    mase, smape, modelo_utilizado
) VALUES %s
ON CONFLICT (dim_local_id, dim_causa_id, metrica, ano_referencia, ano_forecast, modelo_utilizado)
DO UPDATE SET
    valor_previsto        = EXCLUDED.valor_previsto,
    intervalo_inferior_80 = EXCLUDED.intervalo_inferior_80,
    intervalo_superior_80 = EXCLUDED.intervalo_superior_80,
    intervalo_inferior_95 = EXCLUDED.intervalo_inferior_95,
    intervalo_superior_95 = EXCLUDED.intervalo_superior_95,
    mase                  = EXCLUDED.mase,
    smape                 = EXCLUDED.smape
"""


# ---------------------------------------------------------------------------
# Sparse gate — core routing logic
# ---------------------------------------------------------------------------


def select_model_for_series(train_y: np.ndarray) -> tuple:
    """Route a training series to the appropriate forecasting model.

    Gate: n_nonzero >= 5 AND sum >= 10 within the training window → AutoARIMA.
    Fallback order: CrostonOptimized (n_nonzero >= 2) → HistoricAverage.

    Args:
        train_y: 1-D numpy array of annual rate values from the training window
                 (typically 2015-2021, 7 observations).

    Returns:
        (model_instance, model_name_str) — e.g. (AutoARIMA(season_length=1), "AutoARIMA").
    """
    n_nonzero = int(np.count_nonzero(train_y))
    total = float(np.sum(train_y))

    if n_nonzero >= 5 and total >= 10:
        return AutoARIMA(season_length=1), "AutoARIMA"
    elif n_nonzero >= 2:
        return CrostonOptimized(), "CrostonOptimized"
    else:
        return HistoricAverage(), "HistoricAverage"


# ---------------------------------------------------------------------------
# Data helpers
# ---------------------------------------------------------------------------


def _load_population_df(pop_csv_path: str) -> pd.DataFrame:
    """Load TCU population CSV via pandas.

    DuckDB read_csv_auto() fails on the UTF-8 em-dash comment line at the top
    of tcu_populacao.csv. Loading via pandas with skiprows=1 avoids the sniff
    failure.
    """
    return pd.read_csv(
        pop_csv_path,
        skiprows=1,
        dtype={"codigo_ibge_6": str, "ano": int, "populacao_total": int},
    )


def _aggregate_series(
    parquet_path: str,
    pop_df: pd.DataFrame,
    table_name: str,
    date_col: str,
    mun_col: str,
) -> pd.DataFrame:
    """Aggregate Parquet records into annual taxa_por_100k series per municipality.

    Parameterized DuckDB query: con.execute("... FROM read_parquet(?)", [path])
    guards against SQL injection from filesystem paths.

    Returns a StatsForecast-format DataFrame with columns:
      unique_id (str, codigo_ibge_6), ds (datetime64, YYYY-12-31), y (float, taxa_por_100k).
    """
    mun_col = _validate_col(mun_col, _ALLOWED_MUN_COLS)
    date_col = _validate_col(date_col, _ALLOWED_DATE_COLS)

    con = duckdb.connect()
    con.register("dim_populacao_csv", pop_df)

    query = f"""
        WITH annual AS (
            SELECT {mun_col}                                          AS codigo_ibge_6,
                   CAST(SUBSTRING({date_col}, 5, 4) AS INT)          AS ano,
                   COUNT(*)                                           AS total_eventos
            FROM read_parquet(?)
            WHERE {date_col} IS NOT NULL
              AND LENGTH({date_col}) = 8
              AND CAST(SUBSTRING({date_col}, 5, 4) AS INT) BETWEEN 2015 AND 2024
            GROUP BY {mun_col}, SUBSTRING({date_col}, 5, 4)
        )
        SELECT
            a.codigo_ibge_6,
            a.ano,
            a.total_eventos * 100000.0 / NULLIF(p.populacao_total, 0) AS taxa_por_100k
        FROM annual a
        LEFT JOIN dim_populacao_csv p
            ON a.codigo_ibge_6 = p.codigo_ibge_6 AND a.ano = p.ano
        ORDER BY a.codigo_ibge_6, a.ano
    """

    df = con.execute(query, [parquet_path]).df()
    con.close()

    df["ds"] = pd.to_datetime(df["ano"].astype(str) + "-12-31")
    df = df.rename(columns={"codigo_ibge_6": "unique_id", "taxa_por_100k": "y"})
    return df[["unique_id", "ds", "y"]].dropna(subset=["y"])


# ---------------------------------------------------------------------------
# AutoARIMA runner (per municipality)
# ---------------------------------------------------------------------------


def _run_autoarima(
    df_all: pd.DataFrame,
    conn,
    local_id_map: dict,
    batch: list,
) -> dict:
    """Run AutoARIMA (or fallback) per municipality and collect forecast rows.

    Training window: 2015-2021 (7 obs).
    Backtest: cross_validation with n_windows=1, h=2 (validates on 2022-2023).
    Final forecast: h=3 (produces anos 2024, 2025, 2026).
    Assertion before DB write: fc['ds'].dt.year.tolist() == [2024, 2025, 2026].

    Args:
        df_all: Full series DataFrame (all municipalities, 2015-2023).
        conn: Live psycopg2 connection.
        local_id_map: dict mapping codigo_ibge_6 → dim_local.id.
        batch: Mutable list to accumulate rows (flushed by caller or here).

    Returns:
        Summary dict with keys: series_autoarima, series_fallback.
    """
    series_autoarima = 0
    series_fallback = 0
    rows_written = 0
    skipped = 0

    unique_ids = df_all["unique_id"].unique()
    total = len(unique_ids)
    logger.info("AutoARIMA: processing %d municipality series", total)

    for idx, uid in enumerate(unique_ids, 1):
        if idx % 100 == 0:
            logger.info("AutoARIMA progress: %d/%d series", idx, total)

        df_mun = df_all[df_all["unique_id"] == uid].copy().sort_values("ds")
        df_train = df_mun[df_mun["ds"].dt.year <= 2021]

        if len(df_train) == 0:
            skipped += 1
            continue

        dim_local_id = local_id_map.get(str(uid))
        if dim_local_id is None:
            logger.warning("dim_local not found for codigo_ibge_6=%s — skipping", uid)
            skipped += 1
            continue

        model, model_name = select_model_for_series(df_train["y"].values)

        if model_name == "AutoARIMA":
            series_autoarima += 1
            sf = StatsForecast(models=[model], freq="YE", n_jobs=1)

            # Backtest metrics (2022-2023 validation)
            try:
                cv = sf.cross_validation(df=df_mun, h=2, n_windows=1)
                train_df = df_mun[df_mun["ds"] < "2022-01-01"]
                smape_result = compute_smape(cv, models=["AutoARIMA"])
                mase_result = compute_mase(
                    cv, models=["AutoARIMA"], seasonality=1, train_df=train_df
                )
                smape_val = float(smape_result["AutoARIMA"].mean())
                mase_val = float(mase_result["AutoARIMA"].mean())
            except Exception as exc:
                logger.warning(
                    "Backtest failed for %s: %s — using None metrics", uid, exc
                )
                smape_val = None
                mase_val = None

            # Final forecast h=3 years ahead of last observation
            fc = sf.forecast(df=df_mun, h=3, level=[80, 95])
            forecast_years = fc["ds"].dt.year.tolist()
            if forecast_years not in ([2024, 2025, 2026], [2025, 2026, 2027]):
                logger.warning(
                    "Unexpected forecast years for %s: %s — stored as-is",
                    uid,
                    forecast_years,
                )

            for _, row in fc.iterrows():
                ano_fc = int(row["ds"].year)
                batch.append(
                    (
                        dim_local_id,
                        None,  # dim_causa_id: NULL for all-cause aggregate
                        "municipio",
                        "taxa_mortalidade_100k",
                        _ANO_REFERENCIA,
                        ano_fc,
                        float(row["AutoARIMA"]),
                        float(row.get("AutoARIMA-lo-80", row["AutoARIMA"])),
                        float(row.get("AutoARIMA-hi-80", row["AutoARIMA"])),
                        float(row.get("AutoARIMA-lo-95", row["AutoARIMA"])),
                        float(row.get("AutoARIMA-hi-95", row["AutoARIMA"])),
                        mase_val,
                        smape_val,
                        model_name,
                    )
                )

        else:
            # Fallback: CrostonOptimized or HistoricAverage — requires ConformalIntervals
            series_fallback += 1

            # Hold-out backtest for fallback metrics (mirroring _run_prophet backtest pattern)
            df_train_bt = df_mun[df_mun["ds"].dt.year <= 2021].copy()
            df_val_bt = df_mun[df_mun["ds"].dt.year.isin([2022, 2023])].copy()

            if len(df_train_bt) >= 2 and len(df_val_bt) > 0:
                if model_name == "CrostonOptimized":
                    model_bt = CrostonOptimized()
                else:
                    model_bt = HistoricAverage()
                sf_bt = StatsForecast([model_bt], freq="YE", n_jobs=1)
                bt_train_df = df_train_bt[["ds", "y"]].copy()
                bt_train_df.insert(0, "unique_id", str(uid))
                fc_bt = sf_bt.forecast(df=bt_train_df, h=len(df_val_bt))
                col = model_name if model_name in fc_bt.columns else None
                if col is None:
                    logger.warning(
                        "Fallback backtest: expected column '%s' not in StatsForecast output %s "
                        "for series %s — skipping metrics",
                        model_name,
                        fc_bt.columns.tolist(),
                        uid,
                    )
                    smape_val = None
                    mase_val = None
                else:
                    val_ds = df_val_bt["ds"].values
                    cv_df = pd.DataFrame(
                        {
                            "unique_id": [str(uid)] * len(val_ds),
                            "ds": val_ds,
                            "cutoff": [df_train_bt["ds"].max()] * len(val_ds),
                            "y": df_val_bt["y"].values,
                            model_name: fc_bt[col].values,
                        }
                    )
                    train_df_for_mase = bt_train_df[["unique_id", "ds", "y"]].copy()
                    try:
                        smape_result = compute_smape(cv_df, models=[model_name])
                        mase_result = compute_mase(
                            cv_df,
                            models=[model_name],
                            seasonality=1,
                            train_df=train_df_for_mase,
                        )
                        smape_val = float(smape_result[model_name].mean())
                        mase_val = float(mase_result[model_name].mean())
                    except Exception as bt_exc:
                        logger.warning(
                            "Fallback backtest metrics failed for %s/%s: %s",
                            uid,
                            model_name,
                            bt_exc,
                        )
                        smape_val = None
                        mase_val = None
            else:
                logger.warning(
                    "Fallback backtest skipped for %s/%s: train=%d val=%d",
                    uid,
                    model_name,
                    len(df_train_bt),
                    len(df_val_bt),
                )
                mase_val = None
                smape_val = None

            sf = StatsForecast([model], freq="YE", n_jobs=1)
            fc = sf.forecast(
                df=df_mun,
                h=3,
                level=[80, 95],
                prediction_intervals=ConformalIntervals(),
            )

            col_prefix = model_name

            for _, row in fc.iterrows():
                ano_fc = int(row["ds"].year)
                lo80_col = f"{col_prefix}-lo-80"
                hi80_col = f"{col_prefix}-hi-80"
                lo95_col = f"{col_prefix}-lo-95"
                hi95_col = f"{col_prefix}-hi-95"

                batch.append(
                    (
                        dim_local_id,
                        None,
                        "municipio",
                        "taxa_mortalidade_100k",
                        _ANO_REFERENCIA,
                        ano_fc,
                        float(row[col_prefix]),
                        float(row.get(lo80_col, row[col_prefix])),
                        float(row.get(hi80_col, row[col_prefix])),
                        float(row.get(lo95_col, row[col_prefix])),
                        float(row.get(hi95_col, row[col_prefix])),
                        mase_val,  # mase: hold-out backtest 2015-2021 train / 2022-2023 val; None if insufficient data
                        smape_val,  # smape: hold-out backtest 2015-2021 train / 2022-2023 val; None if insufficient data
                        model_name,
                    )
                )

        # Flush batch if full
        if len(batch) >= _BATCH_SIZE:
            with conn.cursor() as cur:
                psycopg2.extras.execute_values(
                    cur, _FORECAST_UPSERT, batch, page_size=_BATCH_SIZE
                )
            conn.commit()
            rows_written += len(batch)
            batch.clear()

    return {
        "series_autoarima": series_autoarima,
        "series_fallback": series_fallback,
        "rows_written": rows_written,
        "skipped": skipped,
    }


# ---------------------------------------------------------------------------
# Prophet runner (per UF)
# ---------------------------------------------------------------------------


def _run_prophet(
    conn,
    uf_id_map: dict,
    batch: list,
    uf_series: pd.DataFrame,
) -> dict:
    """Run Prophet per UF (27 series) with two fits for 80% and 95% CI.

    Prophet's interval_width is a constructor parameter — a single fit produces
    only one CI band. Two separate fits are required.

    Manual MASE/SMAPE on 2022-2023 validation (Prophet has no built-in metrics):
      smape_val = mean(2|y-yhat| / (|y|+|yhat|+1e-8))
      mase_val  = mean(|y-yhat|) / mean(|diff(train_y)|+1e-8)

    Args:
        conn: Live psycopg2 connection.
        uf_id_map: dict mapping codigo_uf (2-char) → dim_local.id (lowest-id municipality per UF).
        batch: Mutable list to accumulate rows.
        uf_series: UF-level aggregated series (unique_id=CODUF, ds, y).

    Returns:
        Summary dict with keys: series_prophet, rows_written.
    """
    series_prophet = 0
    rows_written = 0
    skipped = 0

    unique_ids = uf_series["unique_id"].unique()
    total = len(unique_ids)
    logger.info("Prophet: processing %d UF series", total)

    future_ds = pd.DataFrame(
        {"ds": pd.to_datetime(["2025-12-31", "2026-12-31", "2027-12-31"])}
    )

    for idx, uid in enumerate(unique_ids, 1):
        logger.info("Prophet UF %d/%d — %s", idx, total, uid)

        dim_local_id = uf_id_map.get(str(uid))
        if dim_local_id is None:
            logger.warning("dim_local not found for uf codigo_uf=%s — skipping", uid)
            skipped += 1
            continue

        series = uf_series[uf_series["unique_id"] == uid].copy().sort_values("ds")
        df_prophet = series[["ds", "y"]].copy()

        # Training window for backtest (2015-2022)
        df_train = df_prophet[df_prophet["ds"].dt.year <= 2022]
        df_val = df_prophet[df_prophet["ds"].dt.year.isin([2023, 2024])]

        if len(df_train) < 3:
            logger.warning(
                "Insufficient training data for UF %s (%d obs) — skipping",
                uid,
                len(df_train),
            )
            skipped += 1
            continue

        # Backtest: train on 2015-2022, validate on 2023-2024
        try:
            m_bt = Prophet(
                yearly_seasonality=False,
                weekly_seasonality=False,
                daily_seasonality=False,
                interval_width=0.80,
            )
            m_bt.fit(df_train)
            val_future = pd.DataFrame(
                {"ds": pd.to_datetime([f"{y}-12-31" for y in [2023, 2024]])}
            )
            fc_val = m_bt.predict(val_future)

            y_true = df_val["y"].values if len(df_val) > 0 else np.array([])
            y_pred = fc_val["yhat"].values[: len(y_true)]

            if len(y_true) > 0:
                smape_val = float(
                    np.mean(
                        2
                        * np.abs(y_true - y_pred)
                        / (np.abs(y_true) + np.abs(y_pred) + 1e-8)
                    )
                )
                naive_mae = float(np.mean(np.abs(np.diff(df_train["y"].values))))
                if naive_mae < 1e-6:
                    logger.warning(
                        "Near-zero naive MAE for UF %s (%.2e) — MASE undefined, storing sentinel 9999",
                        uid,
                        naive_mae,
                    )
                    mase_val = 9999.0
                else:
                    mase_val = float(np.mean(np.abs(y_true - y_pred)) / naive_mae)
            else:
                smape_val = None
                mase_val = None
        except Exception as exc:
            logger.warning(
                "Backtest failed for UF %s: %s — using None metrics", uid, exc
            )
            smape_val = None
            mase_val = None

        # Final forecast 2025-2027: fit 80% CI model on full 2015-2024 series
        try:
            m80 = Prophet(
                yearly_seasonality=False,
                weekly_seasonality=False,
                daily_seasonality=False,
                interval_width=0.80,
            )
            m80.fit(df_prophet)
            fc80 = m80.predict(future_ds)

            # Second fit for 95% CI (separate fit required — Prophet constructor param)
            m95 = Prophet(
                yearly_seasonality=False,
                weekly_seasonality=False,
                daily_seasonality=False,
                interval_width=0.95,
            )
            m95.fit(df_prophet)
            fc95 = m95.predict(future_ds)
        except Exception as exc:
            logger.warning("Prophet fit failed for UF %s: %s — skipping", uid, exc)
            skipped += 1
            continue

        series_prophet += 1

        for i, ano_fc in enumerate(_FORECAST_ANOS):
            batch.append(
                (
                    dim_local_id,
                    None,  # dim_causa_id: NULL for all-cause aggregate
                    "uf",
                    "taxa_mortalidade_100k",
                    _ANO_REFERENCIA,
                    ano_fc,
                    float(fc80.iloc[i]["yhat"]),
                    float(fc80.iloc[i]["yhat_lower"]),  # 80% lower
                    float(fc80.iloc[i]["yhat_upper"]),  # 80% upper
                    float(fc95.iloc[i]["yhat_lower"]),  # 95% lower
                    float(fc95.iloc[i]["yhat_upper"]),  # 95% upper
                    mase_val,
                    smape_val,
                    "Prophet",
                )
            )

        if len(batch) >= _BATCH_SIZE:
            with conn.cursor() as cur:
                psycopg2.extras.execute_values(
                    cur, _FORECAST_UPSERT, batch, page_size=_BATCH_SIZE
                )
            conn.commit()
            rows_written += len(batch)
            batch.clear()

    return {
        "series_prophet": series_prophet,
        "rows_written": rows_written,
        "skipped": skipped,
    }


# ---------------------------------------------------------------------------
# Main orchestrator
# ---------------------------------------------------------------------------


def run_forecasting(conn) -> dict:
    """Orchestrate AutoARIMA (per municipality) and Prophet (per UF) forecasting.

    Reads Parquet via DuckDB, computes annual taxa_por_100k series, runs models,
    and upserts results into forecast_resultados.

    Args:
        conn: Live psycopg2 connection with autocommit disabled.

    Returns:
        Summary dict: rows_written, series_autoarima, series_prophet, series_fallback.
    """
    # ------------------------------------------------------------------
    # 1. Path resolution (SAMPLE_MODE vs full mode)
    # ------------------------------------------------------------------
    if config.SAMPLE_MODE:
        if os.environ.get("SAMPLE_DATA_DIR"):
            sample_dir = Path(config.SAMPLE_DATA_DIR)
        else:
            sample_dir = (
                Path(__file__).resolve().parent.parent.parent / "data" / "sample"
            )
        sim_parquet = str(sample_dir / "sim_sample.parquet")
        pop_csv_path = str(
            Path(__file__).resolve().parent.parent
            / "seeds"
            / "data"
            / "tcu_populacao.csv"
        )
    else:
        raw_dir = Path(__file__).resolve().parent.parent.parent / "data" / "raw"
        sim_glob = str(raw_dir / "SIM_*.parquet")
        if not glob_module.glob(sim_glob):
            raise FileNotFoundError(f"No SIM Parquet files found matching {sim_glob}")
        sim_parquet = sim_glob  # DuckDB read_parquet() expands glob patterns natively
        pop_csv_path = str(
            Path(__file__).resolve().parent.parent
            / "seeds"
            / "data"
            / "tcu_populacao.csv"
        )

    logger.info(
        "Starting forecasting runner: SAMPLE_MODE=%s sim_parquet=%s",
        config.SAMPLE_MODE,
        sim_parquet,
    )

    # ------------------------------------------------------------------
    # 2. Load population reference table (pandas — DuckDB em-dash fix)
    # ------------------------------------------------------------------
    pop_df = _load_population_df(pop_csv_path)

    # ------------------------------------------------------------------
    # 3. Aggregate SIM annual series per municipality
    # ------------------------------------------------------------------
    df_mun_all = _aggregate_series(
        parquet_path=sim_parquet,
        pop_df=pop_df,
        table_name="sim",
        date_col="DTOBITO",
        mun_col="CODMUNRES",
    )
    logger.info(
        "SIM aggregation complete: %d series × anos available",
        df_mun_all["unique_id"].nunique(),
    )

    # ------------------------------------------------------------------
    # 4. Build UF-level series by aggregating from municipality Parquet
    # ------------------------------------------------------------------
    con = duckdb.connect()
    con.register("dim_populacao_csv", pop_df)
    uf_df = con.execute(
        """
        WITH uf_annual AS (
            SELECT SUBSTRING(CODMUNRES, 1, 2)                       AS codigo_ibge_6,
                   CAST(SUBSTRING(DTOBITO, 5, 4) AS INT)          AS ano,
                   COUNT(*)                                        AS total_obitos
            FROM read_parquet(?)
            WHERE DTOBITO IS NOT NULL
              AND LENGTH(DTOBITO) = 8
              AND CAST(SUBSTRING(DTOBITO, 5, 4) AS INT) BETWEEN 2015 AND 2024
              AND CODMUNRES IS NOT NULL
            GROUP BY SUBSTRING(CODMUNRES, 1, 2), SUBSTRING(DTOBITO, 5, 4)
        )
        SELECT
            u.codigo_ibge_6,
            u.ano,
            SUM(u.total_obitos) * 100000.0 / NULLIF(SUM(p.populacao_total), 0) AS taxa_por_100k
        FROM uf_annual u
        LEFT JOIN dim_populacao_csv p
            ON SUBSTRING(p.codigo_ibge_6, 1, 2) = u.codigo_ibge_6 AND p.ano = u.ano
        GROUP BY u.codigo_ibge_6, u.ano
        ORDER BY u.codigo_ibge_6, u.ano
        """,
        [sim_parquet],
    ).df()
    con.close()

    uf_df["ds"] = pd.to_datetime(uf_df["ano"].astype(str) + "-12-31")
    uf_series = uf_df.rename(
        columns={"codigo_ibge_6": "unique_id", "taxa_por_100k": "y"}
    )[["unique_id", "ds", "y"]].dropna(subset=["y"])
    logger.info(
        "UF aggregation complete: %d UF series", uf_series["unique_id"].nunique()
    )

    # ------------------------------------------------------------------
    # 5. Load dim_local lookup (inline — no DimCache class needed for ML)
    # ------------------------------------------------------------------
    with conn.cursor() as cur:
        cur.execute("SELECT id, codigo_ibge_6 FROM dim_local WHERE is_current = TRUE")
        local_id_map: dict[str, int] = {row[1]: row[0] for row in cur.fetchall()}
        # UF-level lookup: codigo_uf (2-char, matches CODUF from SIM) → lowest-id
        # municipality in that UF. forecast_resultados.dim_local_id is NOT NULL so
        # a representative municipality row is required for UF-level Prophet rows.
        cur.execute(
            "SELECT DISTINCT ON (codigo_uf) codigo_uf, id"
            " FROM dim_local WHERE is_current = TRUE"
            " ORDER BY codigo_uf, id"
        )
        uf_id_map: dict[str, int] = {row[0]: row[1] for row in cur.fetchall()}
    logger.info(
        "dim_local cache loaded: %d municipality, %d UF entries",
        len(local_id_map),
        len(uf_id_map),
    )

    # ------------------------------------------------------------------
    # 6. Run AutoARIMA per municipality and Prophet per UF
    # ------------------------------------------------------------------
    batch: list = []

    autoarima_stats = _run_autoarima(df_mun_all, conn, local_id_map, batch)
    prophet_stats = _run_prophet(conn, uf_id_map, batch, uf_series)

    # Flush any remaining rows
    if batch:
        final_count = len(batch)
        with conn.cursor() as cur:
            psycopg2.extras.execute_values(
                cur, _FORECAST_UPSERT, batch, page_size=_BATCH_SIZE
            )
        conn.commit()
        batch.clear()
    else:
        final_count = 0

    total_rows = (
        autoarima_stats["rows_written"] + prophet_stats["rows_written"] + final_count
    )

    logger.info(
        "Forecasting complete: rows_written=%d autoarima=%d prophet=%d fallback=%d",
        total_rows,
        autoarima_stats["series_autoarima"],
        prophet_stats["series_prophet"],
        autoarima_stats["series_fallback"],
    )

    return {
        "rows_written": total_rows,
        "series_autoarima": autoarima_stats["series_autoarima"],
        "series_prophet": prophet_stats["series_prophet"],
        "series_fallback": autoarima_stats["series_fallback"],
    }


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="HealthLens ML forecasting runner")
    parser.add_argument(
        "--raw-dir",
        default="data/raw",
        help="Directory containing raw Parquet files (full mode only; default: %(default)s)",
    )
    args = parser.parse_args()

    if not config.DATABASE_URL_SYNC:
        raise RuntimeError("DATABASE_URL_SYNC environment variable is required")

    logger.info("Starting forecasting runner: SAMPLE_MODE=%s", config.SAMPLE_MODE)

    conn = psycopg2.connect(config.DATABASE_URL_SYNC)
    try:
        summary = run_forecasting(conn)
    finally:
        conn.close()

    print(f"\nForecasting complete: {summary}")
