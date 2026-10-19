"""Regression tests for the SINAN (agravo, ano) orchestration loop in
etl.pipeline.run_pipeline.

Pins the SINAN integration contract: the loop iterates at the
(agravo, ano) grain — never (agravo, UF), because pysus.sinan() has no
state= parameter — and every audit write for a loaded SINAN unit passes
uf=None and fonte="SINAN", legal only from migration 0019
onward. Also pins the resume path: a unit whose hash is already recorded
in audit_ingestao must skip stage_sinan/load_notificacoes cleanly, and a
unit absent from the pysus catalog must not raise.

All tests are pure-Python / mocked-DB / mocked-collaborator — no network
access and no PostgreSQL required.

Run with:
    cd backend && SAMPLE_MODE=true pytest tests/test_etl_pipeline_sinan.py -v
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
        patch(
            "etl.pipeline.stage_sinan", side_effect=lambda df, **kw: df
        ) as mock_stage_sinan,
        patch("etl.pipeline.load_obitos", return_value=10) as mock_load_obitos,
        patch(
            "etl.pipeline.load_internacoes", return_value=20
        ) as mock_load_internacoes,
        patch(
            "etl.pipeline.load_notificacoes", return_value=5
        ) as mock_load_notificacoes,
        patch(
            "etl.pipeline.pd.read_parquet", return_value=trivial_df
        ) as mock_read_parquet,
        patch("etl.pipeline._write_audit") as mock_write_audit,
    ):
        mock_dim_cache_cls.return_value.load_all = MagicMock()
        yield {
            "stage_sim": mock_stage_sim,
            "stage_sih": mock_stage_sih,
            "stage_sinan": mock_stage_sinan,
            "load_obitos": mock_load_obitos,
            "load_internacoes": mock_load_internacoes,
            "load_notificacoes": mock_load_notificacoes,
            "read_parquet": mock_read_parquet,
            "write_audit": mock_write_audit,
        }


def _sinan_result(agravo, ano):
    return (
        Path(f"data/raw/SINAN_{agravo}_{ano}.parquet"),
        f"hash-sinan-{agravo}-{ano}",
    )


def _sinan_result_side_effect(agravo, ano, raw_dir):
    """side_effect wrapper matching get_or_download_sinan's 3-arg signature."""
    return _sinan_result(agravo, ano)


# ---------------------------------------------------------------------------
# (agravo, ano) grain — no UF dimension, exactly 4 calls for 2 agravos x 2 anos
# ---------------------------------------------------------------------------


def test_sinan_units_are_agravo_ano_grain_not_agravo_uf(_mock_collaborators):
    conn = _fake_conn()

    with (
        patch(
            "etl.pipeline.get_or_download_sinan", side_effect=_sinan_result_side_effect
        ) as mock_get_or_download_sinan,
        patch("etl.pipeline.get_or_download_sim", return_value=None),
        patch("etl.pipeline.get_or_download_sih", return_value=None),
        patch("etl.pipeline._already_loaded", return_value=False),
    ):
        summary = pipeline.run_pipeline(
            ufs=[],
            anos=[2022, 2023],
            raw_dir=Path("data/raw"),
            conn=conn,
            agravos=["DENG", "ANIM"],
        )

    assert mock_get_or_download_sinan.call_count == 4
    for call in mock_get_or_download_sinan.call_args_list:
        args = call.args
        kwargs = call.kwargs
        all_values = list(args) + list(kwargs.values())
        assert "SP" not in all_values and "RJ" not in all_values
    assert summary["sinan_files"] == 4


# ---------------------------------------------------------------------------
# stage_sinan called once per loaded unit with tipo_agravo == unit's agravo
# ---------------------------------------------------------------------------


def test_stage_sinan_called_with_correct_tipo_agravo(_mock_collaborators):
    conn = _fake_conn()

    with (
        patch(
            "etl.pipeline.get_or_download_sinan", side_effect=_sinan_result_side_effect
        ),
        patch("etl.pipeline.get_or_download_sim", return_value=None),
        patch("etl.pipeline.get_or_download_sih", return_value=None),
        patch("etl.pipeline._already_loaded", return_value=False),
    ):
        pipeline.run_pipeline(
            ufs=[],
            anos=[2023],
            raw_dir=Path("data/raw"),
            conn=conn,
            agravos=["DENG", "ANIM"],
        )

    stage_sinan_mock = _mock_collaborators["stage_sinan"]
    assert stage_sinan_mock.call_count == 2
    called_agravos = {
        call.kwargs.get("tipo_agravo") for call in stage_sinan_mock.call_args_list
    }
    assert called_agravos == {"DENG", "ANIM"}


# ---------------------------------------------------------------------------
# _write_audit called with uf=None, real ano, fonte="SINAN" for each loaded unit
# ---------------------------------------------------------------------------


def test_write_audit_called_with_uf_none_and_fonte_sinan(_mock_collaborators):
    conn = _fake_conn()

    with (
        patch(
            "etl.pipeline.get_or_download_sinan", side_effect=_sinan_result_side_effect
        ),
        patch("etl.pipeline.get_or_download_sim", return_value=None),
        patch("etl.pipeline.get_or_download_sih", return_value=None),
        patch("etl.pipeline._already_loaded", return_value=False),
    ):
        pipeline.run_pipeline(
            ufs=[],
            anos=[2023],
            raw_dir=Path("data/raw"),
            conn=conn,
            agravos=["DENG"],
        )

    write_audit_mock = _mock_collaborators["write_audit"]
    write_audit_mock.assert_called_once()
    args = write_audit_mock.call_args.args
    kwargs = write_audit_mock.call_args.kwargs

    # positional signature: (conn, arquivo, hash_md5, uf, ano, fonte)
    if len(args) >= 6:
        uf_value = args[3]
        ano_value = args[4]
        fonte_value = args[5]
    else:
        uf_value = kwargs.get("uf", args[3] if len(args) > 3 else None)
        ano_value = kwargs.get("ano", args[4] if len(args) > 4 else None)
        fonte_value = kwargs.get("fonte", args[-1] if args else None)

    assert uf_value is None
    assert ano_value == 2023
    assert fonte_value == "SINAN"


# ---------------------------------------------------------------------------
# Already-loaded SINAN unit: skip counter increments, no stage/load call
# ---------------------------------------------------------------------------


def test_already_loaded_sinan_unit_skips_stage_and_load(_mock_collaborators):
    conn = _fake_conn()

    def fake_already_loaded(conn, hash_md5):
        return hash_md5 == "hash-sinan-DENG-2023"

    with (
        patch(
            "etl.pipeline.get_or_download_sinan", side_effect=_sinan_result_side_effect
        ),
        patch("etl.pipeline.get_or_download_sim", return_value=None),
        patch("etl.pipeline.get_or_download_sih", return_value=None),
        patch("etl.pipeline._already_loaded", side_effect=fake_already_loaded),
    ):
        summary = pipeline.run_pipeline(
            ufs=[],
            anos=[2023],
            raw_dir=Path("data/raw"),
            conn=conn,
            agravos=["DENG", "ANIM"],
        )

    assert summary["sinan_skipped_loaded"] == 1
    # 2 units total, 1 already loaded -> load_notificacoes called one time
    # fewer than the number of units (1 call, not 2)
    assert _mock_collaborators["load_notificacoes"].call_count == 1
    assert _mock_collaborators["stage_sinan"].call_count == 1


# ---------------------------------------------------------------------------
# Unit absent from catalog: increments sinan_skipped_absent, does not raise
# ---------------------------------------------------------------------------


def test_sinan_unit_absent_from_catalog_increments_absent_counter(_mock_collaborators):
    conn = _fake_conn()

    with (
        patch("etl.pipeline.get_or_download_sinan", return_value=None),
        patch("etl.pipeline.get_or_download_sim", return_value=None),
        patch("etl.pipeline.get_or_download_sih", return_value=None),
    ):
        summary = pipeline.run_pipeline(
            ufs=[],
            anos=[2023],
            raw_dir=Path("data/raw"),
            conn=conn,
            agravos=["DENG"],
        )

    assert summary["sinan_skipped_absent"] == 1
    assert summary["sinan_files"] == 0
    _mock_collaborators["read_parquet"].assert_not_called()


# ---------------------------------------------------------------------------
# sinan_only=True skips SIM and SIH entirely
# ---------------------------------------------------------------------------


def test_sinan_only_skips_sim_and_sih(_mock_collaborators):
    conn = _fake_conn()

    with (
        patch(
            "etl.pipeline.get_or_download_sinan", side_effect=_sinan_result_side_effect
        ),
        patch("etl.pipeline.get_or_download_sim") as mock_get_or_download_sim,
        patch("etl.pipeline.get_or_download_sih") as mock_get_or_download_sih,
        patch("etl.pipeline._already_loaded", return_value=False),
    ):
        pipeline.run_pipeline(
            ufs=["SP"],
            anos=[2023],
            raw_dir=Path("data/raw"),
            conn=conn,
            agravos=["DENG"],
            sinan_only=True,
        )

    mock_get_or_download_sim.assert_not_called()
    mock_get_or_download_sih.assert_not_called()


# ---------------------------------------------------------------------------
# sih_only=True skips SIM but still runs SIH for every UF x ano unit
# ---------------------------------------------------------------------------


def test_sih_only_skips_sim_and_runs_sih(_mock_collaborators):
    conn = _fake_conn()

    with (
        patch("etl.pipeline.get_or_download_sim") as mock_get_or_download_sim,
        patch(
            "etl.pipeline.get_or_download_sih", return_value=None
        ) as mock_get_or_download_sih,
    ):
        summary = pipeline.run_pipeline(
            ufs=["SP", "AC"],
            anos=[2025],
            raw_dir=Path("data/raw"),
            conn=conn,
            sih_only=True,
        )

    mock_get_or_download_sim.assert_not_called()
    assert mock_get_or_download_sih.call_count == 2
    assert summary["sim_skipped_absent"] == 0
    assert summary["sih_skipped_absent"] == 2


# ---------------------------------------------------------------------------
# Zero units loaded: the open read transaction must be committed before the
# aggregate refresh switches to autocommit (psycopg2 raises otherwise)
# ---------------------------------------------------------------------------


class _TxStrictConn:
    """Mimics psycopg2: any cursor use opens a transaction, and setting
    autocommit while a transaction is open raises ProgrammingError."""

    def __init__(self):
        self._autocommit = False
        self.in_tx = False
        self._cur = MagicMock()
        self._cur.fetchone.return_value = (0,)
        self._cur.fetchall.return_value = []

    def cursor(self):
        if not self._autocommit:
            self.in_tx = True
        return self._cur

    def commit(self):
        self.in_tx = False

    @property
    def autocommit(self):
        return self._autocommit

    @autocommit.setter
    def autocommit(self, value):
        if self.in_tx:
            raise RuntimeError("set_session cannot be used inside a transaction")
        self._autocommit = value


def test_refresh_does_not_fail_when_no_unit_was_loaded(_mock_collaborators):
    conn = _TxStrictConn()
    conn.cursor()  # DimCache / _already_loaded SELECTs leave a read tx open

    with patch("etl.pipeline.get_or_download_sinan", return_value=None):
        summary = pipeline.run_pipeline(
            ufs=[],
            anos=[2025],
            raw_dir=Path("data/raw"),
            conn=conn,
            agravos=["CHIK"],
            sinan_only=True,
        )

    assert summary["sinan_skipped_absent"] == 1
    assert conn.autocommit is False


# ---------------------------------------------------------------------------
# No agravos argument at all: zero SINAN calls, all four keys default to 0
# ---------------------------------------------------------------------------


def test_no_agravos_argument_runs_zero_sinan_calls(_mock_collaborators):
    conn = _fake_conn()

    with (
        patch("etl.pipeline.get_or_download_sinan") as mock_get_or_download_sinan,
        patch("etl.pipeline.get_or_download_sim", return_value=None),
        patch("etl.pipeline.get_or_download_sih", return_value=None),
    ):
        summary = pipeline.run_pipeline(
            ufs=[], anos=[2023], raw_dir=Path("data/raw"), conn=conn
        )

    mock_get_or_download_sinan.assert_not_called()
    assert summary["sinan_files"] == 0
    assert summary["sinan_rows"] == 0
    assert summary["sinan_skipped_loaded"] == 0
    assert summary["sinan_skipped_absent"] == 0


# ---------------------------------------------------------------------------
# Summary dict always contains all four SINAN keys
# ---------------------------------------------------------------------------


def test_summary_dict_contains_all_four_sinan_keys(_mock_collaborators):
    conn = _fake_conn()

    with (
        patch("etl.pipeline.get_or_download_sinan", return_value=None),
        patch("etl.pipeline.get_or_download_sim", return_value=None),
        patch("etl.pipeline.get_or_download_sih", return_value=None),
    ):
        summary = pipeline.run_pipeline(
            ufs=[], anos=[2023], raw_dir=Path("data/raw"), conn=conn, agravos=["DENG"]
        )

    expected_keys = {
        "sinan_files",
        "sinan_rows",
        "sinan_skipped_loaded",
        "sinan_skipped_absent",
    }
    assert expected_keys.issubset(summary.keys())
