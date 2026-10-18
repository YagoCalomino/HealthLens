"""Unit tests for scripts/assert_ml_snapshots.py.

All tests use a MagicMock DB connection (no live database). scripts/ lives
at repo root, not inside backend/ -- add it to sys.path, mirroring the
pattern used by backend/tests/test_scripts_assert_sinan_completeness.py.

Run with:
    cd backend && SAMPLE_MODE=true pytest tests/test_scripts_assert_ml_snapshots.py -v
"""

import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import assert_ml_snapshots as m  # noqa: E402 — import after sys.path setup


# ---------------------------------------------------------------------------
# check_cluster_snapshots
# ---------------------------------------------------------------------------


def test_check_cluster_snapshots_two_years_three_apart_passes():
    ok, msg = m.check_cluster_snapshots([2021, 2024])
    assert ok is True
    assert "2021" in msg and "2024" in msg


def test_check_cluster_snapshots_gap_too_small_fails():
    ok, msg = m.check_cluster_snapshots([2021, 2023])
    assert ok is False


def test_check_cluster_snapshots_single_year_fails():
    ok, msg = m.check_cluster_snapshots([2023])
    assert ok is False


def test_check_cluster_snapshots_empty_fails():
    ok, msg = m.check_cluster_snapshots([])
    assert ok is False


def test_check_cluster_snapshots_extra_prior_year_does_not_break_gate():
    # A pre-existing 2023 snapshot alongside the two required years
    # must not fail the gate -- it coexists harmlessly.
    ok, msg = m.check_cluster_snapshots([2021, 2023, 2024])
    assert ok is True


# ---------------------------------------------------------------------------
# check_forecast_currency
# ---------------------------------------------------------------------------


def test_check_forecast_currency_2024_anchor_correct_horizon_passes():
    ok, msg = m.check_forecast_currency([2024], [2025, 2026, 2027])
    assert ok is True


def test_check_forecast_currency_wrong_anchor_fails():
    ok, msg = m.check_forecast_currency([2023], [2024, 2025, 2026])
    assert ok is False


def test_check_forecast_currency_partial_retrain_mixed_years_fails():
    ok, msg = m.check_forecast_currency([2023, 2024], [2025, 2026, 2027])
    assert ok is False


def test_check_forecast_currency_short_series_extra_past_years_passes():
    # Municípios with short historical series (e.g. RJ sample data starting
    # only in 2023) get forecasts anchored to their own last available year,
    # so ano_forecast legitimately includes 2023/2024 alongside 2025-2027.
    # That's correct per-município behavior, not a partial retrain.
    ok, msg = m.check_forecast_currency([2024], [2023, 2024, 2025, 2026, 2027])
    assert ok is True


def test_check_forecast_currency_missing_future_year_fails():
    # A missing year from the expected future horizon must still fail, even
    # though extra past years are now tolerated.
    ok, msg = m.check_forecast_currency([2024], [2023, 2025, 2026])
    assert ok is False
    assert "2027" in msg


# ---------------------------------------------------------------------------
# check_mv_freshness
# ---------------------------------------------------------------------------


def test_check_mv_freshness_2024_passes():
    ok, msg = m.check_mv_freshness(2024)
    assert ok is True


def test_check_mv_freshness_stale_2023_fails_with_remediation():
    ok, msg = m.check_mv_freshness(2023)
    assert ok is False
    assert "REFRESH MATERIALIZED VIEW" in msg


def test_check_mv_freshness_none_fails():
    ok, msg = m.check_mv_freshness(None)
    assert ok is False


# ---------------------------------------------------------------------------
# run_checks (mocked connection, all queries pass)
# ---------------------------------------------------------------------------


def _mock_conn(
    cluster_anos_rows,
    cluster_counts_rows,
    forecast_ref_rows,
    forecast_horizon_rows,
    mv_max_ano_row,
):
    """Build a MagicMock connection whose cursor() issues, in the exact
    order run_checks calls them: cluster_anos, cluster_counts,
    forecast_ano_referencia, forecast_ano_forecast, mv_max_ano.
    """
    conn = MagicMock()
    cur = MagicMock()
    cur.fetchall.side_effect = [
        cluster_anos_rows,
        cluster_counts_rows,
        forecast_ref_rows,
        forecast_horizon_rows,
    ]
    cur.fetchone.return_value = mv_max_ano_row
    conn.cursor.return_value = cur
    return conn


def test_run_checks_all_pass_returns_result_dict():
    conn = _mock_conn(
        cluster_anos_rows=[(2021,), (2024,)],
        cluster_counts_rows=[(2021, 5570), (2024, 5570)],
        forecast_ref_rows=[(2024,)],
        forecast_horizon_rows=[(2025,), (2026,), (2027,)],
        mv_max_ano_row=(2024,),
    )
    result = m.run_checks(conn)
    assert result["cluster_anos"] == [2021, 2024]
    assert result["mv_max_ano"] == 2024


def test_run_checks_zero_row_snapshot_fails():
    conn = _mock_conn(
        cluster_anos_rows=[(2021,), (2024,)],
        cluster_counts_rows=[(2021, 0), (2024, 5570)],
        forecast_ref_rows=[(2024,)],
        forecast_horizon_rows=[(2025,), (2026,), (2027,)],
        mv_max_ano_row=(2024,),
    )
    with pytest.raises(AssertionError, match="zero linhas"):
        m.run_checks(conn)


def test_run_checks_stale_mv_fails():
    conn = _mock_conn(
        cluster_anos_rows=[(2021,), (2024,)],
        cluster_counts_rows=[(2021, 5570), (2024, 5570)],
        forecast_ref_rows=[(2024,)],
        forecast_horizon_rows=[(2025,), (2026,), (2027,)],
        mv_max_ano_row=(2023,),
    )
    with pytest.raises(AssertionError, match="REFRESH MATERIALIZED VIEW"):
        m.run_checks(conn)


def test_run_checks_partial_retrain_fails():
    conn = _mock_conn(
        cluster_anos_rows=[(2021,), (2024,)],
        cluster_counts_rows=[(2021, 5570), (2024, 5570)],
        forecast_ref_rows=[(2023,), (2024,)],
        forecast_horizon_rows=[(2025,), (2026,), (2027,)],
        mv_max_ano_row=(2024,),
    )
    with pytest.raises(AssertionError, match="forecast currency"):
        m.run_checks(conn)
