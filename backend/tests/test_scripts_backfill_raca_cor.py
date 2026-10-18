"""Unit tests for scripts/backfill_raca_cor.py.

All tests use a MagicMock DB connection/cursor (no live database) and
tmp_path-seeded real Parquet fixture files -- this script actually parses
Parquet content via stage_sim(), unlike scripts/reset_sih_data.py which only
globs and unlinks files. scripts/ lives at repo root, not inside backend/ --
add it to sys.path, mirroring backend/tests/test_scripts_reset_sih_data.py.

Run with:
    cd backend && SAMPLE_MODE=true pytest tests/test_scripts_backfill_raca_cor.py -v
"""

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))
sys.path.insert(0, str(REPO_ROOT / "backend"))

import backfill_raca_cor as m  # noqa: E402 -- import after sys.path setup
from etl.staging.sim_staging import stage_sim  # noqa: E402


def _sim_df(contadores, racacores, codmunres="120010", dtobito="21042022"):
    """Build a minimal real-shaped SIM DataFrame (no NUMERODO -- real pysus shape)."""
    n = len(contadores)
    return pd.DataFrame(
        {
            "DTOBITO": [dtobito] * n,
            "CAUSABAS": ["I219"] * n,
            "CODMUNRES": [codmunres] * n,
            "SEXO": ["1"] * n,
            "IDADE": [450] * n,
            "CONTADOR": contadores,
            "RACACOR": racacores,
        }
    )


def _write_sim_parquet(tmp_path, uf, ano, contadores, racacores, **kwargs):
    df = _sim_df(contadores, racacores, **kwargs)
    path = tmp_path / f"SIM_{uf}_{ano}.parquet"
    df.to_parquet(path)
    return path


def _mock_conn():
    conn = MagicMock()
    cur = MagicMock()
    conn.cursor.return_value = cur
    return conn, cur


# --- 1. Filename parsing ---


def test_filename_parsing_skips_unparseable_files(tmp_path):
    _write_sim_parquet(tmp_path, "AC", 2024, [1, 2], ["4", "1"])
    # NOTSIM_XX.parquet does not even match the SIM_*.parquet glob, so it is
    # never seen by the scan at all -- only files matching the glob but
    # failing the anchored uf/ano regex count toward files_skipped_unparseable.
    (tmp_path / "NOTSIM_XX.parquet").write_bytes(b"not-sim-data")
    (tmp_path / "SIM_bogus.parquet").write_bytes(b"bad-name")

    conn, cur = _mock_conn()

    result = m.backfill_raca_cor(conn, tmp_path, dry_run=True)

    assert result["files_scanned"] == 1
    assert result["files_skipped_unparseable"] == 1


# --- 2. Dry-run purity ---


def test_dry_run_issues_no_update_and_no_commit(tmp_path):
    _write_sim_parquet(tmp_path, "AC", 2024, [1, 2, 3], ["4", "1", "2"])
    conn, cur = _mock_conn()

    result = m.backfill_raca_cor(conn, tmp_path, dry_run=True)

    conn.commit.assert_not_called()
    for call in cur.execute.call_args_list:
        assert "UPDATE" not in str(call)
    with patch("backfill_raca_cor.psycopg2.extras.execute_batch") as mock_batch:
        m.backfill_raca_cor(conn, tmp_path, dry_run=True)
        mock_batch.assert_not_called()
    assert result["rows_read"] > 0


# --- 3. UPDATE parameter shape ---


def test_update_parameter_shape(tmp_path):
    _write_sim_parquet(tmp_path, "AC", 2024, [1, 2], ["4", "1"])
    conn, cur = _mock_conn()

    with patch("backfill_raca_cor.psycopg2.extras.execute_batch") as mock_batch:
        m.backfill_raca_cor(conn, tmp_path, dry_run=False)

    assert mock_batch.call_count >= 1
    call = mock_batch.call_args_list[0]
    sql_arg = call.args[1]
    batch_arg = call.args[2]
    assert sql_arg == "UPDATE fato_obitos SET raca_cor = %s WHERE numero_do = %s"
    for raca_cor_val, numero_do_val in batch_arg:
        assert isinstance(numero_do_val, str)
        assert raca_cor_val is not None


# --- 4. Blank handling ---


def test_blank_raca_cor_counted_and_excluded_from_update(tmp_path):
    _write_sim_parquet(tmp_path, "AC", 2024, [1, 2], ["4", ""])
    conn, cur = _mock_conn()

    with patch("backfill_raca_cor.psycopg2.extras.execute_batch") as mock_batch:
        result = m.backfill_raca_cor(conn, tmp_path, dry_run=False)

    assert result["source_blank"] == 1

    staged = stage_sim(_sim_df([1, 2], ["4", ""]), uf="AC", ano=2024)
    blank_numero_do = staged.loc[staged["raca_cor"].isna(), "numero_do"].tolist()

    sent_numero_dos = []
    for call in mock_batch.call_args_list:
        batch_arg = call.args[2]
        sent_numero_dos.extend(numero_do for _, numero_do in batch_arg)

    for nd in blank_numero_do:
        assert nd not in sent_numero_dos


# --- 5. numero_do parity ---


def test_numero_do_parity_with_stage_sim(tmp_path):
    _write_sim_parquet(tmp_path, "AC", 2024, [1, 2, 3], ["4", "1", "2"])
    conn, cur = _mock_conn()

    with patch("backfill_raca_cor.psycopg2.extras.execute_batch") as mock_batch:
        m.backfill_raca_cor(conn, tmp_path, dry_run=False)

    expected = stage_sim(_sim_df([1, 2, 3], ["4", "1", "2"]), uf="AC", ano=2024)[
        "numero_do"
    ].tolist()

    sent_numero_dos = []
    for call in mock_batch.call_args_list:
        batch_arg = call.args[2]
        sent_numero_dos.extend(numero_do for _, numero_do in batch_arg)

    assert sorted(sent_numero_dos) == sorted(expected)


# --- 6. --uf/--ano scoping ---


def test_uf_scoping_skips_other_ufs(tmp_path):
    _write_sim_parquet(tmp_path, "AC", 2024, [1], ["4"])
    _write_sim_parquet(tmp_path, "SP", 2024, [1], ["1"])
    conn, cur = _mock_conn()

    result = m.backfill_raca_cor(conn, tmp_path, dry_run=True, ufs=["AC"])

    assert result["files_scanned"] == 1
    assert result["per_file"][0]["uf"] == "AC"


def test_ano_scoping_skips_other_years(tmp_path):
    _write_sim_parquet(tmp_path, "AC", 2023, [1], ["4"])
    _write_sim_parquet(tmp_path, "AC", 2024, [1], ["1"])
    conn, cur = _mock_conn()

    result = m.backfill_raca_cor(conn, tmp_path, dry_run=True, anos=[2024])

    assert result["files_scanned"] == 1
    assert result["per_file"][0]["ano"] == 2024


# --- 7. Verify math ---


def test_verify_raca_cor_computes_delta_and_flips_pass(tmp_path):
    _write_sim_parquet(tmp_path, "AC", 2024, [1, 2, 3, 4], ["4", "1", "2", ""])
    conn, cur = _mock_conn()

    # source_blank_pct = 25.0 (1 of 4 blank)
    # db_null_pct within tolerance: db_rows=4, db_null=1 -> 25.0, delta=0
    cur.fetchone.side_effect = [(4,), (1,)]
    cur.fetchall.return_value = [("1", 1), ("2", 1), ("4", 1), (None, 1)]

    result = m.verify_raca_cor(conn, tmp_path, tolerance_pct=1.0)

    assert result["source_blank_pct"] == pytest.approx(25.0)
    assert result["db_null_pct"] == pytest.approx(25.0)
    assert result["delta_pct"] == pytest.approx(0.0)
    assert result["passed"] is True

    # Now push db_null_pct far outside tolerance
    conn2, cur2 = _mock_conn()
    cur2.fetchone.side_effect = [(4,), (4,)]  # db_null_pct = 100.0
    cur2.fetchall.return_value = [(None, 4)]

    result2 = m.verify_raca_cor(conn2, tmp_path, tolerance_pct=1.0)

    assert result2["passed"] is False


def test_verify_raca_cor_issues_only_select(tmp_path):
    _write_sim_parquet(tmp_path, "AC", 2024, [1], ["4"])
    conn, cur = _mock_conn()
    cur.fetchone.side_effect = [(1,), (0,)]
    cur.fetchall.return_value = [("4", 1)]

    m.verify_raca_cor(conn, tmp_path, tolerance_pct=1.0)

    for call in cur.execute.call_args_list:
        sql = call.args[0].upper()
        assert "UPDATE" not in sql
        assert "DELETE" not in sql
        assert "INSERT" not in sql
        assert sql.strip().startswith("SELECT")


# --- CLI guard ---


def test_cli_without_flags_makes_no_db_call(monkeypatch):
    monkeypatch.setattr(sys, "argv", ["backfill_raca_cor.py"])

    with patch("backfill_raca_cor.psycopg2.connect") as mock_connect:
        exit_code = m.main()

    mock_connect.assert_not_called()
    assert exit_code == 1
