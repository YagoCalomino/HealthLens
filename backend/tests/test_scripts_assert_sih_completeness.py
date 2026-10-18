"""Unit tests for scripts/assert_sih_completeness.py.

All tests use a MagicMock DB connection (no live database) and tmp_path
YAML files for the allowlist. scripts/ lives at repo root, not inside
backend/ -- add it to sys.path.

Run with:
    cd backend && SAMPLE_MODE=true pytest tests/test_scripts_assert_sih_completeness.py -v
"""

import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import assert_sih_completeness as m  # noqa: E402 — import after sys.path setup


def _mock_conn(rows: list[tuple[str, int, int]]):
    """Build a MagicMock connection whose cursor().fetchall() returns `rows`."""
    conn = MagicMock()
    cur = MagicMock()
    cur.fetchall.return_value = rows
    conn.cursor.return_value = cur
    return conn


def test_all_present_and_nonzero_passes():
    conn = _mock_conn(
        [("SP", 2022, 100), ("SP", 2023, 50), ("AC", 2022, 10), ("AC", 2023, 5)]
    )
    result = m.assert_sih_completeness(
        conn, allowlist=set(), ufs=["SP", "AC"], anos=[2022, 2023]
    )
    assert result["checked"] == 4
    assert result["total_rows"] == 165


def test_one_missing_combo_no_allowlist_raises():
    conn = _mock_conn([("SP", 2022, 100), ("SP", 2023, 50), ("AC", 2022, 10)])
    with pytest.raises(AssertionError, match="AC/2023"):
        m.assert_sih_completeness(
            conn, allowlist=set(), ufs=["SP", "AC"], anos=[2022, 2023]
        )


def test_allowlisted_missing_combo_passes():
    conn = _mock_conn([("SP", 2022, 100), ("SP", 2023, 50), ("AC", 2022, 10)])
    result = m.assert_sih_completeness(
        conn,
        allowlist={("AC", 2023)},
        ufs=["SP", "AC"],
        anos=[2022, 2023],
    )
    assert result["checked"] == 4
    assert ("AC", 2023) in result["allowlisted"]


def test_allowlist_entry_does_not_mask_different_missing_combo():
    # AC/2023 is allowlisted but SP/2023 is genuinely missing and unexplained.
    conn = _mock_conn([("SP", 2022, 100), ("AC", 2022, 10)])
    with pytest.raises(AssertionError, match="SP/2023"):
        m.assert_sih_completeness(
            conn,
            allowlist={("AC", 2023)},
            ufs=["SP", "AC"],
            anos=[2022, 2023],
        )


def test_present_but_below_min_rows_fails_like_absent():
    conn = _mock_conn(
        [("SP", 2022, 100), ("SP", 2023, 50), ("AC", 2022, 3), ("AC", 2023, 5)]
    )
    with pytest.raises(AssertionError, match="AC/2022"):
        m.assert_sih_completeness(
            conn, allowlist=set(), ufs=["SP", "AC"], anos=[2022, 2023], min_rows=5
        )


def test_uf_and_ano_narrow_the_grid():
    conn = _mock_conn([("SP", 2022, 100)])
    result = m.assert_sih_completeness(conn, allowlist=set(), ufs=["SP"], anos=[2022])
    assert result["checked"] == 1


def test_missing_allowlist_file_treated_as_empty(tmp_path):
    missing_path = tmp_path / "does_not_exist.yaml"
    allowlist = m.load_allowlist(str(missing_path))
    assert allowlist == set()


def test_load_allowlist_parses_known_absent(tmp_path):
    allowlist_path = tmp_path / "allowlist.yaml"
    allowlist_path.write_text("known_absent:\n  - [sp, 2005]\n  - [AC, 2011]\n")
    allowlist = m.load_allowlist(str(allowlist_path))
    assert allowlist == {("SP", 2005), ("AC", 2011)}


def test_grid_constants():
    assert len(m.ALL_UFS) == 27
    assert m.ALL_YEARS[0] == 2010
    assert m.ALL_YEARS[-1] == 2024
