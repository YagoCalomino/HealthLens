"""Unit tests for scripts/fix_sim_date_corruption.py.

All tests use a MagicMock DB connection/cursor (no live database) and
tmp_path-seeded real Parquet fixture files, mirroring
backend/tests/test_scripts_backfill_raca_cor.py's conventions. scripts/
lives at repo root, not inside backend/ -- added to sys.path.

Run with:
    cd backend && SAMPLE_MODE=true pytest tests/test_scripts_fix_sim_date_corruption.py -v
"""

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))
sys.path.insert(0, str(REPO_ROOT / "backend"))

import fix_sim_date_corruption as m  # noqa: E402 -- import after sys.path setup


def _sim_df(contadores, dtobito="15062022", codmunres="355030"):
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
            "CODUF": ["35"] * n,
        }
    )


def _write_sim_parquet(tmp_path, uf, ano, contadores, **kwargs):
    df = _sim_df(contadores, **kwargs)
    path = tmp_path / f"SIM_{uf}_{ano}.parquet"
    df.to_parquet(path)
    return path


def _mock_conn():
    conn = MagicMock()
    cur = MagicMock()
    conn.cursor.return_value = cur
    return conn, cur


# --- 1. Nothing to do ---


def test_no_corrupted_rows_short_circuits(tmp_path):
    conn, cur = _mock_conn()
    cur.fetchall.return_value = []  # dim_tempo WHERE ano > 2025 -> empty

    result = m.fix_sim_date_corruption(conn, tmp_path, dry_run=True)

    assert result["corrupted_tempo_rows"] == 0
    assert result["numero_dos_fixed"] == 0
    conn.commit.assert_not_called()


# --- 2. Dry-run purity ---


def test_dry_run_issues_no_update_no_insert_no_commit(tmp_path):
    _write_sim_parquet(tmp_path, "SP", 2022, [1])
    conn, cur = _mock_conn()
    # order: corrupted fetchall, affected-count fetchone, affected-distinct fetchall, tempo_cache fetchall
    cur.fetchall.side_effect = [
        [(999, 3112)],  # find_corrupted_tempo_ids
        [("DO202235000001",)],  # find_affected_numero_dos (distinct)
        [],  # _load_tempo_cache (empty -- forces placeholder path)
    ]
    cur.fetchone.side_effect = [(1,)]  # find_affected_numero_dos (count)

    with patch("fix_sim_date_corruption.psycopg2.extras.execute_batch") as mock_batch:
        result = m.fix_sim_date_corruption(conn, tmp_path, dry_run=True)
        mock_batch.assert_not_called()

    conn.commit.assert_not_called()
    for call in cur.execute.call_args_list:
        sql = str(call).upper()
        assert "UPDATE" not in sql
        assert "INSERT" not in sql

    assert result["numero_dos_fixed"] == 1
    assert result["rows_updated"] == 0
    assert result["numero_dos_not_matched"] == 0


# --- 3. Matched repair (cache hit, no INSERT needed) ---


def test_matched_row_updates_dim_tempo_id(tmp_path):
    _write_sim_parquet(tmp_path, "SP", 2022, [1])
    conn, cur = _mock_conn()
    cur.fetchall.side_effect = [
        [(999, 3112)],  # find_corrupted_tempo_ids
        [("DO202235000001",)],  # find_affected_numero_dos (distinct)
        [(42, 2022, 6)],  # _load_tempo_cache -- (2022, 6) already exists as id=42
    ]
    cur.fetchone.side_effect = [(1,)]  # find_affected_numero_dos (count)

    with patch("fix_sim_date_corruption.psycopg2.extras.execute_batch") as mock_batch:
        result = m.fix_sim_date_corruption(conn, tmp_path, dry_run=False)

    assert result["numero_dos_fixed"] == 1
    assert result["rows_updated"] == 1
    assert result["numero_dos_not_matched"] == 0

    mock_batch.assert_called_once()
    call = mock_batch.call_args
    sql_arg = call.args[1]
    batch_arg = call.args[2]
    assert sql_arg == "UPDATE fato_obitos SET dim_tempo_id = %s WHERE numero_do = %s"
    assert batch_arg == [(42, "DO202235000001")]
    conn.commit.assert_called()


# --- 4. Unmatched numero_do ---


def test_unmatched_numero_do_reported(tmp_path):
    # No SIM_*.parquet files at all in tmp_path
    conn, cur = _mock_conn()
    cur.fetchall.side_effect = [
        [(999, 3112)],
        [("DO202235000001",)],
        [],
    ]
    cur.fetchone.side_effect = [(1,)]

    result = m.fix_sim_date_corruption(conn, tmp_path, dry_run=True)

    assert result["numero_dos_fixed"] == 0
    assert result["numero_dos_not_matched"] == 1
    assert result["unmatched_numero_dos"] == ["DO202235000001"]


# --- 5. Filename parsing (shared helper) ---


def test_filename_parsing_skips_unparseable_files(tmp_path):
    _write_sim_parquet(tmp_path, "AC", 2024, [1, 2])
    (tmp_path / "NOTSIM_XX.parquet").write_bytes(b"not-sim-data")
    (tmp_path / "SIM_bogus.parquet").write_bytes(b"bad-name")

    matched, skipped = m._iter_sim_files(tmp_path, None, None)

    assert len(matched) == 1
    assert skipped == 1


def test_uf_ano_scoping(tmp_path):
    _write_sim_parquet(tmp_path, "AC", 2023, [1])
    _write_sim_parquet(tmp_path, "SP", 2024, [1])

    matched, _ = m._iter_sim_files(tmp_path, ["SP"], [2024])

    assert len(matched) == 1
    assert matched[0][1] == "SP"
    assert matched[0][2] == 2024


# --- 6. Idempotency ---


def test_second_run_is_a_no_op_once_fixed(tmp_path):
    """Once dim_tempo_id no longer points at a corrupted row, a re-run finds nothing."""
    conn, cur = _mock_conn()
    # Second run: dim_tempo WHERE ano > 2025 is now empty (already repaired).
    cur.fetchall.return_value = []

    result = m.fix_sim_date_corruption(conn, tmp_path, dry_run=False)

    assert result["corrupted_tempo_rows"] == 0
    assert result["rows_updated"] == 0
    conn.commit.assert_not_called()


# --- CLI guard ---


def test_cli_without_flags_makes_no_db_call(monkeypatch):
    monkeypatch.setattr(sys, "argv", ["fix_sim_date_corruption.py"])

    with patch("fix_sim_date_corruption.psycopg2.connect") as mock_connect:
        exit_code = m.main()

    mock_connect.assert_not_called()
    assert exit_code == 1
