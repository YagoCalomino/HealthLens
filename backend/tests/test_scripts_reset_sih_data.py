"""Unit tests for scripts/reset_sih_data.py.

All tests use a MagicMock DB connection/cursor (no live database) and
tmp_path-seeded Parquet fixture files. scripts/ lives at repo root, not
inside backend/ -- add it to sys.path.

Run with:
    cd backend && SAMPLE_MODE=true pytest tests/test_scripts_reset_sih_data.py -v
"""

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch


REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import reset_sih_data as m  # noqa: E402 — import after sys.path setup


def _mock_conn(rowcounts=(3, 2)):
    conn = MagicMock()
    cur = MagicMock()
    cur.rowcount_iter = iter(rowcounts)

    def _execute(sql, *args, **kwargs):
        pass

    cur.execute.side_effect = _execute
    conn.cursor.return_value = cur
    return conn, cur


def test_delete_order_fato_before_audit_then_commit(tmp_path):
    conn, cur = _mock_conn()
    cur.rowcount = (
        0  # simplest: constant across both DELETEs, order still checked below
    )

    m.reset_sih_data(conn, tmp_path)

    executed_sql = [call.args[0] for call in cur.execute.call_args_list]
    assert executed_sql[0] == "DELETE FROM fato_internacoes"
    assert executed_sql[1] == "DELETE FROM audit_ingestao WHERE fonte = 'SIH'"
    conn.commit.assert_called_once()
    # commit must happen after both DELETEs (mock_calls tracks the full nested
    # call sequence across conn.cursor() and conn.commit(), unlike method_calls
    # which only records top-level calls).
    call_names = [str(c) for c in conn.mock_calls]
    commit_index = next(i for i, c in enumerate(call_names) if "commit()" in c)
    execute_indices = [i for i, c in enumerate(call_names) if ".execute(" in c]
    assert commit_index > max(execute_indices)


def test_sim_parquet_files_survive(tmp_path):
    (tmp_path / "SIM_SP_2022.parquet").write_bytes(b"sim-data")
    (tmp_path / "SIH_SP_2022.parquet").write_bytes(b"sih-data")

    conn, cur = _mock_conn()
    cur.rowcount = 0

    m.reset_sih_data(conn, tmp_path)

    assert (tmp_path / "SIM_SP_2022.parquet").exists()


def test_sih_parquet_files_removed(tmp_path):
    (tmp_path / "SIH_SP_2022.parquet").write_bytes(b"sih-data")
    (tmp_path / "SIH_AC_2023.parquet").write_bytes(b"sih-data-2")

    conn, cur = _mock_conn()
    cur.rowcount = 0

    result = m.reset_sih_data(conn, tmp_path)

    assert not (tmp_path / "SIH_SP_2022.parquet").exists()
    assert not (tmp_path / "SIH_AC_2023.parquet").exists()
    assert result["cache_files_deleted"] == 2


def test_missing_raw_dir_does_not_raise(tmp_path):
    missing_dir = tmp_path / "does_not_exist"
    conn, cur = _mock_conn()
    cur.rowcount = 0

    result = m.reset_sih_data(conn, missing_dir)

    assert result["cache_files_deleted"] == 0


def test_cli_without_confirm_makes_no_db_call(monkeypatch, tmp_path):
    monkeypatch.setattr(sys, "argv", ["reset_sih_data.py", "--raw-dir", str(tmp_path)])

    with patch("reset_sih_data.psycopg2.connect") as mock_connect:
        exit_code = m.main()

    mock_connect.assert_not_called()
    assert exit_code != 0


def test_dry_run_reports_without_deleting(tmp_path, monkeypatch):
    (tmp_path / "SIH_SP_2022.parquet").write_bytes(b"sih-data")
    monkeypatch.setattr(
        sys, "argv", ["reset_sih_data.py", "--raw-dir", str(tmp_path), "--dry-run"]
    )
    monkeypatch.setenv("DATABASE_URL_SYNC", "postgresql://fake/db")

    conn = MagicMock()
    cur = MagicMock()
    cur.fetchone.side_effect = [(5,), (3,)]
    conn.cursor.return_value = cur

    with patch("reset_sih_data.psycopg2.connect", return_value=conn) as mock_connect:
        exit_code = m.main()

    mock_connect.assert_called_once()
    cur.execute.assert_any_call("SELECT COUNT(*) FROM fato_internacoes")
    conn.commit.assert_not_called()
    assert (tmp_path / "SIH_SP_2022.parquet").exists()
    assert exit_code == 0


def test_rerunning_reset_is_idempotent_noop(tmp_path):
    conn, cur = _mock_conn()
    cur.rowcount = 0

    first = m.reset_sih_data(conn, tmp_path)
    second = m.reset_sih_data(conn, tmp_path)

    assert first["cache_files_deleted"] == 0
    assert second["cache_files_deleted"] == 0
