"""Regression tests for the resume/checkpoint path in etl.pipeline.run_pipeline.

Pins the resumability contract: a resumed run whose SIM/SIH units are
already recorded in ``audit_ingestao`` must skip cleanly (no re-download,
no re-load, no crash) and the run summary must report exactly how many
(UF, ano) units were loaded / already-loaded / absent-from-catalog, for
both SIM and SIH.

All tests are pure-Python / mocked-DB / mocked-ingestor — no network access
and no PostgreSQL required.

Run with:
    cd backend && SAMPLE_MODE=true pytest tests/test_etl_pipeline_resume.py -v
"""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

from etl import pipeline


def _fake_conn():
    """A MagicMock connection whose cursor satisfies the tail-work queries
    (materialized view refresh + TABNET cross-validation SELECT)."""
    conn = MagicMock()
    cur = MagicMock()
    cur.fetchone.return_value = (0,)
    cur.fetchall.return_value = []
    conn.cursor.return_value = cur
    return conn


@pytest.fixture(autouse=True)
def _sample_mode_off():
    """Force full-mode (SAMPLE_MODE=False) so the download/audit branch runs,
    regardless of the SAMPLE_MODE env var set globally in conftest.py."""
    with patch("etl.pipeline.config.SAMPLE_MODE", False):
        yield


@pytest.fixture(autouse=True)
def _mock_collaborators():
    """Patch every collaborator imported into etl.pipeline's namespace so no
    real download, staging, DB load, or Parquet read ever occurs."""
    trivial_df = pd.DataFrame({"col": [1, 2, 3]})

    with (
        patch("etl.pipeline.DimCache") as mock_dim_cache_cls,
        patch(
            "etl.pipeline.stage_sim", side_effect=lambda df, **kw: df
        ) as mock_stage_sim,
        patch(
            "etl.pipeline.stage_sih", side_effect=lambda df, **kw: df
        ) as mock_stage_sih,
        patch("etl.pipeline.load_obitos", return_value=10) as mock_load_obitos,
        patch(
            "etl.pipeline.load_internacoes", return_value=20
        ) as mock_load_internacoes,
        patch(
            "etl.pipeline.pd.read_parquet", return_value=trivial_df
        ) as mock_read_parquet,
        patch("etl.pipeline._write_audit") as mock_write_audit,
    ):
        mock_dim_cache_cls.return_value.load_all = MagicMock()
        yield {
            "stage_sim": mock_stage_sim,
            "stage_sih": mock_stage_sih,
            "load_obitos": mock_load_obitos,
            "load_internacoes": mock_load_internacoes,
            "read_parquet": mock_read_parquet,
            "write_audit": mock_write_audit,
        }


def _sih_result(uf, ano):
    return (Path(f"data/raw/SIH_{uf}_{ano}.parquet"), f"hash-sih-{uf}-{ano}")


def _sim_result(uf, ano):
    return (Path(f"data/raw/SIM_{uf}_{ano}.parquet"), f"hash-sim-{uf}-{ano}")


# ---------------------------------------------------------------------------
# Load-bearing regression: first SIH unit already loaded must not raise
# ---------------------------------------------------------------------------


def test_resumed_run_first_sih_unit_already_loaded_does_not_raise(_mock_collaborators):
    conn = _fake_conn()

    with (
        patch("etl.pipeline.get_or_download_sim", return_value=_sim_result("SP", 2023)),
        patch("etl.pipeline.get_or_download_sih", return_value=_sih_result("SP", 2023)),
        patch("etl.pipeline._already_loaded", return_value=True),
    ):
        # Before the fix, this raises NameError: name 'n' is not defined
        summary = pipeline.run_pipeline(["SP"], [2023], Path("data/raw"), conn)

    assert summary["sih_files"] == 0
    assert summary["sih_rows"] == 0


# ---------------------------------------------------------------------------
# Already-loaded SIH unit: no stage/load/write_audit call, skip counter incremented
# ---------------------------------------------------------------------------


def test_already_loaded_sih_unit_skips_stage_and_load(_mock_collaborators):
    conn = _fake_conn()

    with (
        patch("etl.pipeline.get_or_download_sim", return_value=None),
        patch("etl.pipeline.get_or_download_sih", return_value=_sih_result("SP", 2023)),
        patch("etl.pipeline._already_loaded", return_value=True),
    ):
        summary = pipeline.run_pipeline(["SP"], [2023], Path("data/raw"), conn)

    _mock_collaborators["stage_sih"].assert_not_called()
    _mock_collaborators["load_internacoes"].assert_not_called()
    _mock_collaborators["write_audit"].assert_not_called()
    assert summary["sih_skipped_loaded"] == 1
    assert summary["sih_files"] == 0
    assert summary["sih_rows"] == 0


# ---------------------------------------------------------------------------
# Already-loaded SIH unit leaves sih_files/sih_rows unchanged, increments counter
# ---------------------------------------------------------------------------


def test_already_loaded_sih_unit_increments_skip_counter_only(_mock_collaborators):
    conn = _fake_conn()

    with (
        patch("etl.pipeline.get_or_download_sim", return_value=None),
        patch("etl.pipeline.get_or_download_sih", return_value=_sih_result("SP", 2023)),
        patch("etl.pipeline._already_loaded", return_value=True),
    ):
        summary = pipeline.run_pipeline(["SP"], [2023], Path("data/raw"), conn)

    assert summary["sih_skipped_loaded"] == 1
    assert summary["sih_files"] == 0
    assert summary["sih_rows"] == 0


# ---------------------------------------------------------------------------
# SIH unit absent from catalog: increments sih_skipped_absent, no read_parquet call
# ---------------------------------------------------------------------------


def test_sih_unit_absent_from_catalog_increments_absent_counter(_mock_collaborators):
    conn = _fake_conn()

    with (
        patch("etl.pipeline.get_or_download_sim", return_value=None),
        patch("etl.pipeline.get_or_download_sih", return_value=None),
    ):
        summary = pipeline.run_pipeline(["SP"], [2023], Path("data/raw"), conn)

    _mock_collaborators["read_parquet"].assert_not_called()
    assert summary["sih_skipped_absent"] == 1
    assert summary["sih_files"] == 0


# ---------------------------------------------------------------------------
# Fresh SIH unit: calls load_internacoes once, writes audit with fonte="SIH",
# increments sih_files/sih_rows
# ---------------------------------------------------------------------------


def test_fresh_sih_unit_loads_and_writes_audit(_mock_collaborators):
    conn = _fake_conn()

    with (
        patch("etl.pipeline.get_or_download_sim", return_value=None),
        patch("etl.pipeline.get_or_download_sih", return_value=_sih_result("SP", 2023)),
        patch("etl.pipeline._already_loaded", return_value=False),
    ):
        summary = pipeline.run_pipeline(["SP"], [2023], Path("data/raw"), conn)

    _mock_collaborators["load_internacoes"].assert_called_once()
    write_audit_mock = _mock_collaborators["write_audit"]
    write_audit_mock.assert_called_once()
    _, kwargs = write_audit_mock.call_args
    args = write_audit_mock.call_args.args
    assert "SIH" in args or kwargs.get("fonte") == "SIH"
    assert summary["sih_files"] == 1
    assert summary["sih_rows"] == 20


# ---------------------------------------------------------------------------
# Same three outcomes for the SIM branch
# ---------------------------------------------------------------------------


def test_already_loaded_sim_unit_skips_stage_and_load(_mock_collaborators):
    conn = _fake_conn()

    with (
        patch("etl.pipeline.get_or_download_sim", return_value=_sim_result("SP", 2023)),
        patch("etl.pipeline.get_or_download_sih", return_value=None),
        patch("etl.pipeline._already_loaded", return_value=True),
    ):
        summary = pipeline.run_pipeline(["SP"], [2023], Path("data/raw"), conn)

    _mock_collaborators["stage_sim"].assert_not_called()
    _mock_collaborators["load_obitos"].assert_not_called()
    _mock_collaborators["write_audit"].assert_not_called()
    assert summary["sim_skipped_loaded"] == 1
    assert summary["sim_files"] == 0
    assert summary["sim_rows"] == 0


def test_sim_unit_absent_from_catalog_increments_absent_counter(_mock_collaborators):
    conn = _fake_conn()

    with (
        patch("etl.pipeline.get_or_download_sim", return_value=None),
        patch("etl.pipeline.get_or_download_sih", return_value=None),
    ):
        summary = pipeline.run_pipeline(["SP"], [2023], Path("data/raw"), conn)

    _mock_collaborators["read_parquet"].assert_not_called()
    assert summary["sim_skipped_absent"] == 1
    assert summary["sim_files"] == 0


def test_fresh_sim_unit_loads_and_writes_audit(_mock_collaborators):
    conn = _fake_conn()

    with (
        patch("etl.pipeline.get_or_download_sim", return_value=_sim_result("SP", 2023)),
        patch("etl.pipeline.get_or_download_sih", return_value=None),
        patch("etl.pipeline._already_loaded", return_value=False),
    ):
        summary = pipeline.run_pipeline(["SP"], [2023], Path("data/raw"), conn)

    _mock_collaborators["load_obitos"].assert_called_once()
    write_audit_mock = _mock_collaborators["write_audit"]
    write_audit_mock.assert_called_once()
    args = write_audit_mock.call_args.args
    kwargs = write_audit_mock.call_args.kwargs
    assert "SIM" in args or kwargs.get("fonte") == "SIM"
    assert summary["sim_files"] == 1
    assert summary["sim_rows"] == 10


# ---------------------------------------------------------------------------
# Mixed run: unit 1 already loaded, unit 2 fresh, unit 3 absent -- exact counters
# ---------------------------------------------------------------------------


def test_mixed_run_produces_exact_expected_counters(_mock_collaborators):
    conn = _fake_conn()
    anos = [2021, 2022, 2023]  # 1: already-loaded, 2: fresh, 3: absent

    def fake_get_or_download_sih(uf, ano, raw_dir):
        if ano == 2023:
            return None
        return _sih_result(uf, ano)

    def fake_get_or_download_sim(uf, ano, raw_dir):
        if ano == 2023:
            return None
        return _sim_result(uf, ano)

    def fake_already_loaded(conn, hash_md5):
        return "2021" in hash_md5

    with (
        patch("etl.pipeline.get_or_download_sim", side_effect=fake_get_or_download_sim),
        patch("etl.pipeline.get_or_download_sih", side_effect=fake_get_or_download_sih),
        patch("etl.pipeline._already_loaded", side_effect=fake_already_loaded),
    ):
        summary = pipeline.run_pipeline(["SP"], anos, Path("data/raw"), conn)

    assert summary["sih_skipped_loaded"] == 1
    assert summary["sih_files"] == 1
    assert summary["sih_skipped_absent"] == 1
    assert summary["sim_skipped_loaded"] == 1
    assert summary["sim_files"] == 1
    assert summary["sim_skipped_absent"] == 1


# ---------------------------------------------------------------------------
# Summary dict contains all eight keys
# ---------------------------------------------------------------------------


def test_summary_dict_contains_all_eight_keys(_mock_collaborators):
    conn = _fake_conn()

    with (
        patch("etl.pipeline.get_or_download_sim", return_value=None),
        patch("etl.pipeline.get_or_download_sih", return_value=None),
    ):
        summary = pipeline.run_pipeline(["SP"], [2023], Path("data/raw"), conn)

    expected_keys = {
        "sim_files",
        "sih_files",
        "sim_rows",
        "sih_rows",
        "sim_skipped_loaded",
        "sih_skipped_loaded",
        "sim_skipped_absent",
        "sih_skipped_absent",
    }
    assert expected_keys.issubset(summary.keys())
