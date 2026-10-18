"""Unit tests for scripts/assert_sim_completeness.py.

All tests use a MagicMock DB connection (no live database) and tmp_path
YAML files for the allowlist. scripts/ lives at repo root, not inside
backend/ -- add it to sys.path, mirroring
backend/tests/test_scripts_assert_sih_completeness.py.

Run with:
    cd backend && SAMPLE_MODE=true pytest tests/test_scripts_assert_sim_completeness.py -v
"""

import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import assert_sim_completeness as m  # noqa: E402 — import after sys.path setup


def _mock_conn(rows: list[tuple[str, int, int]], dup_count: int = 0):
    """Build a MagicMock connection whose cursor().fetchall() returns `rows`
    and whose cursor().fetchone() returns a canned duplicate-numero_do count.
    """
    conn = MagicMock()
    cur = MagicMock()
    cur.fetchall.return_value = rows
    cur.fetchone.return_value = (dup_count,)
    conn.cursor.return_value = cur
    return conn


def test_full_coverage_passes():
    conn = _mock_conn(
        [("SP", 2022, 100), ("SP", 2023, 50), ("AC", 2022, 10), ("AC", 2023, 5)]
    )
    result = m.assert_sim_completeness(
        conn, allowlist=set(), ufs=["SP", "AC"], anos=[2022, 2023]
    )
    assert result["checked"] == 4
    assert result["total_rows"] == 165


def test_missing_combo_fails():
    conn = _mock_conn([("SP", 2022, 100), ("SP", 2023, 50), ("AC", 2022, 10)])
    with pytest.raises(AssertionError, match="AC/2023"):
        m.assert_sim_completeness(
            conn, allowlist=set(), ufs=["SP", "AC"], anos=[2022, 2023]
        )


def test_below_min_rows_fails():
    conn = _mock_conn(
        [("SP", 2022, 100), ("SP", 2023, 50), ("AC", 2022, 0), ("AC", 2023, 5)]
    )
    with pytest.raises(AssertionError, match="AC/2022"):
        m.assert_sim_completeness(
            conn, allowlist=set(), ufs=["SP", "AC"], anos=[2022, 2023], min_rows=100
        )


def test_allowlist_suppresses_only_its_own_entry():
    # AC/2023 is allowlisted but SP/2023 is genuinely missing and unexplained.
    conn = _mock_conn([("SP", 2022, 100), ("AC", 2022, 10)])
    with pytest.raises(AssertionError) as exc_info:
        m.assert_sim_completeness(
            conn,
            allowlist={("AC", 2023)},
            ufs=["SP", "AC"],
            anos=[2022, 2023],
        )
    msg = str(exc_info.value)
    assert "SP/2023" in msg
    assert "AC/2023" not in msg


def test_load_allowlist_parses_known_absent(tmp_path):
    allowlist_path = tmp_path / "allowlist.yaml"
    allowlist_path.write_text("known_absent:\n  - [sp, 2005]\n  - [AC, 2011]\n")
    allowlist = m.load_allowlist(str(allowlist_path))
    assert allowlist == {("SP", 2005), ("AC", 2011)}
    assert all(isinstance(uf, str) and isinstance(ano, int) for uf, ano in allowlist)


def test_load_allowlist_missing_file_returns_empty_set():
    allowlist = m.load_allowlist("/path/that/does/not/exist.yaml")
    assert allowlist == set()


def test_coverage_2024_breakout():
    conn = _mock_conn(
        [("SP", 2024, 300), ("SP", 2023, 50), ("AC", 2024, 20), ("AC", 2023, 5)]
    )
    result = m.assert_sim_completeness(
        conn, allowlist=set(), ufs=["SP", "AC"], anos=[2023, 2024]
    )
    assert result["coverage_2024"] == {"SP": 300, "AC": 20}


def test_coverage_2024_reports_zero_for_uf_absent_in_2024():
    conn = _mock_conn([("SP", 2023, 50), ("AC", 2023, 5)])
    result = m.assert_sim_completeness(
        conn,
        allowlist={("SP", 2024), ("AC", 2024)},
        ufs=["SP", "AC"],
        anos=[2023, 2024],
    )
    assert result["coverage_2024"] == {"SP": 0, "AC": 0}


def test_assert_no_duplicate_numerodo_returns_count_without_raising():
    conn = _mock_conn([], dup_count=7)
    count = m.assert_no_duplicate_numerodo(conn)
    assert count == 7


def test_assert_no_duplicate_numerodo_zero():
    conn = _mock_conn([], dup_count=0)
    count = m.assert_no_duplicate_numerodo(conn)
    assert count == 0


def test_grid_constants():
    assert len(m.ALL_UFS) == 27
    assert m.ALL_YEARS[0] == 2010
    assert m.ALL_YEARS[-1] == 2024
