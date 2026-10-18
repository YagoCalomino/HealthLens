"""Unit tests for scripts/backfill_dt_notific.py.

All tests use a MagicMock DB connection/cursor (no live database) and
tmp_path-seeded real Parquet fixture files -- this script parses Parquet
content via stage_sinan(), same precedent as
backend/tests/test_scripts_backfill_raca_cor.py. scripts/ lives at repo
root, not inside backend/ -- add it to sys.path.

Run with:
    cd backend && SAMPLE_MODE=true pytest tests/test_scripts_backfill_dt_notific.py -v
"""

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))
sys.path.insert(0, str(REPO_ROOT / "backend"))

import backfill_dt_notific as m  # noqa: E402 -- import after sys.path setup
from etl.staging.sinan_staging import stage_sinan  # noqa: E402


def _sinan_deng_df(n=2, dt_notific=("15012023", "20012023")):
    return pd.DataFrame(
        {
            "DT_NOTIFIC": list(dt_notific[:n])
            if len(dt_notific) >= n
            else list(dt_notific) * n,
            "ID_MN_RESI": ["354990"] * n,
            "CS_SEXO": ["F", "M"][:n],
            "NU_IDADE_N": ["4025", "4040"][:n],
            "CLASSI_FIN": ["10", "12"][:n],
            "NU_NOTIFIC": [f"NOTIF{i}" for i in range(n)],
        }
    )


def _write_sinan_parquet(tmp_path, agravo, ano, n=2, **kwargs):
    df = _sinan_deng_df(n=n, **kwargs)
    path = tmp_path / f"SINAN_{agravo}_{ano}.parquet"
    df.to_parquet(path)
    return path


def _mock_conn():
    conn = MagicMock()
    cur = MagicMock()
    conn.cursor.return_value = cur
    return conn, cur


# --- 1. Filename parsing ---


def test_filename_parsing_skips_unparseable_files(tmp_path):
    _write_sinan_parquet(tmp_path, "DENG", 2023, n=2)
    (tmp_path / "NOTSINAN_XX.parquet").write_bytes(b"not-sinan-data")
    (tmp_path / "SINAN_bogus.parquet").write_bytes(b"bad-name")

    conn, cur = _mock_conn()

    result = m.backfill_dt_notific(conn, tmp_path, dry_run=True)

    assert result["files_scanned"] == 1
    assert result["files_skipped_unparseable"] == 1


# --- 2. Dry-run purity ---


def test_dry_run_issues_no_update_and_no_commit(tmp_path):
    _write_sinan_parquet(tmp_path, "DENG", 2023, n=2)
    conn, cur = _mock_conn()

    result = m.backfill_dt_notific(conn, tmp_path, dry_run=True)

    conn.commit.assert_not_called()
    with patch("backfill_dt_notific.psycopg2.extras.execute_batch") as mock_batch:
        m.backfill_dt_notific(conn, tmp_path, dry_run=True)
        mock_batch.assert_not_called()
    assert result["rows_read"] > 0


# --- 3. --confirm UPDATE parameter shape ---


def test_confirm_update_parameter_shape(tmp_path):
    _write_sinan_parquet(tmp_path, "DENG", 2023, n=2)
    conn, cur = _mock_conn()

    with patch("backfill_dt_notific.psycopg2.extras.execute_batch") as mock_batch:
        m.backfill_dt_notific(conn, tmp_path, dry_run=False)

    assert mock_batch.call_count >= 1
    call = mock_batch.call_args_list[0]
    sql_arg = call.args[1]
    batch_arg = call.args[2]
    assert sql_arg == (
        "UPDATE fato_notificacoes SET dt_notific = %s "
        "WHERE numero_notificacao = %s AND tipo_agravo = %s"
    )
    for dt_notific_val, numero_notificacao_val, tipo_agravo_val in batch_arg:
        assert isinstance(numero_notificacao_val, str)
        assert tipo_agravo_val == "DENG"
        assert dt_notific_val is not None


def test_confirm_batches_are_no_string_formatted_sql(tmp_path):
    _write_sinan_parquet(tmp_path, "DENG", 2023, n=2)
    conn, cur = _mock_conn()

    with patch("backfill_dt_notific.psycopg2.extras.execute_batch") as mock_batch:
        m.backfill_dt_notific(conn, tmp_path, dry_run=False)

    call = mock_batch.call_args_list[0]
    sql_arg = call.args[1]
    assert "%s" in sql_arg
    assert "{" not in sql_arg
    assert "%d" not in sql_arg


# --- 4. numero_notificacao / tipo_agravo / dt_notific parity with stage_sinan ---


def test_matched_key_parity_with_stage_sinan(tmp_path):
    _write_sinan_parquet(tmp_path, "DENG", 2023, n=2)
    conn, cur = _mock_conn()

    with patch("backfill_dt_notific.psycopg2.extras.execute_batch") as mock_batch:
        m.backfill_dt_notific(conn, tmp_path, dry_run=False)

    expected = stage_sinan(_sinan_deng_df(n=2), "DENG")
    expected_keys = set(
        zip(
            expected["numero_notificacao"].tolist(),
            expected["tipo_agravo"].tolist(),
        )
    )

    sent_keys = set()
    for call in mock_batch.call_args_list:
        batch_arg = call.args[2]
        sent_keys.update(
            (numero_notificacao, tipo_agravo)
            for _, numero_notificacao, tipo_agravo in batch_arg
        )

    assert sent_keys == expected_keys


# --- 5. --agravo/--ano scoping ---


def test_agravo_scoping_skips_other_agravos(tmp_path):
    _write_sinan_parquet(tmp_path, "DENG", 2023, n=1)
    _write_sinan_parquet(tmp_path, "ANIM", 2023, n=1)
    conn, cur = _mock_conn()

    result = m.backfill_dt_notific(conn, tmp_path, dry_run=True, agravos=["DENG"])

    assert result["files_scanned"] == 1
    assert result["per_file"][0]["agravo"] == "DENG"


def test_ano_scoping_skips_other_years(tmp_path):
    _write_sinan_parquet(tmp_path, "DENG", 2022, n=1)
    _write_sinan_parquet(tmp_path, "DENG", 2023, n=1)
    conn, cur = _mock_conn()

    result = m.backfill_dt_notific(conn, tmp_path, dry_run=True, anos=[2023])

    assert result["files_scanned"] == 1
    assert result["per_file"][0]["ano"] == 2023


# --- 6. Verify pass/fail ---


def test_verify_pass_when_all_matched_rows_non_null(tmp_path):
    _write_sinan_parquet(tmp_path, "DENG", 2023, n=2)
    conn, cur = _mock_conn()
    cur.fetchone.return_value = (0,)

    result = m.verify_dt_notific(conn, tmp_path)

    assert result["shortfall"] == 0
    assert result["passed"] is True


def test_verify_fail_when_shortfall_rows_exist(tmp_path):
    _write_sinan_parquet(tmp_path, "DENG", 2023, n=2)
    conn, cur = _mock_conn()
    cur.fetchone.return_value = (2,)

    result = m.verify_dt_notific(conn, tmp_path)

    assert result["shortfall"] == 2
    assert result["passed"] is False


def test_verify_issues_only_select(tmp_path):
    _write_sinan_parquet(tmp_path, "DENG", 2023, n=1)
    conn, cur = _mock_conn()
    cur.fetchone.return_value = (0,)

    m.verify_dt_notific(conn, tmp_path)

    for call in cur.execute.call_args_list:
        sql = call.args[0].upper()
        assert "UPDATE" not in sql
        assert "DELETE" not in sql
        assert "INSERT" not in sql
        assert sql.strip().startswith("SELECT")


# --- CLI guard ---


def test_cli_without_flags_makes_no_db_call(monkeypatch):
    monkeypatch.setattr(sys, "argv", ["backfill_dt_notific.py"])

    with patch("backfill_dt_notific.psycopg2.connect") as mock_connect:
        exit_code = m.main()

    mock_connect.assert_not_called()
    assert exit_code == 1


def test_cli_dry_run_makes_no_update(monkeypatch, tmp_path):
    _write_sinan_parquet(tmp_path, "DENG", 2023, n=1)
    monkeypatch.setattr(
        sys, "argv", ["backfill_dt_notific.py", "--dry-run", "--raw-dir", str(tmp_path)]
    )
    monkeypatch.setenv("DATABASE_URL_SYNC", "postgresql://fake")

    with patch("backfill_dt_notific.psycopg2.connect") as mock_connect:
        mock_conn = MagicMock()
        mock_connect.return_value = mock_conn
        exit_code = m.main()

    assert exit_code == 0
    mock_conn.commit.assert_not_called()
