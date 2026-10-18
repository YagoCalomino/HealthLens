"""Unit tests for scripts/assert_sinan_completeness.py.

All tests use a MagicMock DB connection (no live database) and tmp_path
YAML files for the allowlist. scripts/ lives at repo root, not inside
backend/ -- add it to sys.path, mirroring the pattern used by
backend/tests/test_scripts_assert_sih_completeness.py.

Run with:
    cd backend && SAMPLE_MODE=true pytest tests/test_scripts_assert_sinan_completeness.py -v
"""

import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import assert_sinan_completeness as m  # noqa: E402 — import after sys.path setup


def _mock_conn(counts_rows: list[tuple[str, int, int]], uf_rows: list[tuple[str, int]]):
    """Build a MagicMock connection whose cursor().fetchall() returns, in
    order, `counts_rows` for the first query (per-(agravo, ano) counts) and
    `uf_rows` for the second query (per-agravo UF coverage).

    assert_sinan_completeness issues two queries against the same cursor in
    that exact order -- `fetchall.side_effect` (not `return_value`) is
    required so each call returns its own result set. If the two queries
    are ever reordered in the implementation, tests built on this helper
    will fail loudly (wrong shape/columns unpacked) rather than silently
    swapping counts and UF-coverage results.
    """
    conn = MagicMock()
    cur = MagicMock()
    cur.fetchall.side_effect = [counts_rows, uf_rows]
    conn.cursor.return_value = cur
    return conn


def _empty_allowlist() -> dict[str, set[tuple[str, int]]]:
    return {"known_absent": set(), "known_partial": set()}


def _full_uf_rows(agravos: list[str], n_ufs: int = 27) -> list[tuple[str, int]]:
    return [(a, n_ufs) for a in agravos]


def test_all_present_and_full_uf_coverage_passes():
    counts = [
        ("DENG", 2022, 1000),
        ("DENG", 2023, 900),
        ("CHIK", 2022, 500),
        ("CHIK", 2023, 480),
    ]
    conn = _mock_conn(counts, _full_uf_rows(["DENG", "CHIK"]))
    result = m.assert_sinan_completeness(
        conn, allowlist=_empty_allowlist(), agravos=["DENG", "CHIK"], anos=[2022, 2023]
    )
    assert result["checked"] == 4
    assert result["total_rows"] == 2880


def test_missing_combo_no_allowlist_raises():
    counts = [
        ("DENG", 2022, 1000),
        ("DENG", 2023, 900),
        ("CHIK", 2022, 500),
    ]
    conn = _mock_conn(counts, _full_uf_rows(["DENG", "CHIK"]))
    with pytest.raises(AssertionError, match="CHIK/2023"):
        m.assert_sinan_completeness(
            conn,
            allowlist=_empty_allowlist(),
            agravos=["DENG", "CHIK"],
            anos=[2022, 2023],
        )


def test_missing_combo_in_known_absent_passes():
    counts = [
        ("DENG", 2022, 1000),
        ("DENG", 2023, 900),
        ("CHIK", 2022, 500),
    ]
    conn = _mock_conn(counts, _full_uf_rows(["DENG", "CHIK"]))
    allowlist = {"known_absent": {("CHIK", 2023)}, "known_partial": set()}
    result = m.assert_sinan_completeness(
        conn, allowlist=allowlist, agravos=["DENG", "CHIK"], anos=[2022, 2023]
    )
    assert ("CHIK", 2023) in result["allowlisted_absent"]


def test_cliff_year_no_allowlist_raises():
    counts = [
        ("ANIM", 2021, 300000),
        ("ANIM", 2022, 280000),
        ("ANIM", 2023, 9000),
    ]
    conn = _mock_conn(counts, _full_uf_rows(["ANIM"]))
    with pytest.raises(AssertionError, match="cliff"):
        m.assert_sinan_completeness(
            conn,
            allowlist=_empty_allowlist(),
            agravos=["ANIM"],
            anos=[2021, 2022, 2023],
        )


def test_cliff_year_in_known_partial_passes():
    counts = [
        ("ANIM", 2021, 300000),
        ("ANIM", 2022, 280000),
        ("ANIM", 2023, 9000),
    ]
    conn = _mock_conn(counts, _full_uf_rows(["ANIM"]))
    allowlist = {"known_absent": set(), "known_partial": {("ANIM", 2023)}}
    result = m.assert_sinan_completeness(
        conn, allowlist=allowlist, agravos=["ANIM"], anos=[2021, 2022, 2023]
    )
    assert ("ANIM", 2023) in result["allowlisted_partial"]
    assert result["total_rows"] == 589000


def test_low_uf_coverage_raises_naming_27():
    counts = [("DENG", 2022, 1000), ("DENG", 2023, 900)]
    conn = _mock_conn(counts, [("DENG", 12)])
    with pytest.raises(AssertionError, match="27"):
        m.assert_sinan_completeness(
            conn, allowlist=_empty_allowlist(), agravos=["DENG"], anos=[2022, 2023]
        )


def test_min_ufs_override_suppresses_uf_failure():
    counts = [("DENG", 2022, 1000), ("DENG", 2023, 900)]
    conn = _mock_conn(counts, [("DENG", 12)])
    result = m.assert_sinan_completeness(
        conn,
        allowlist=_empty_allowlist(),
        agravos=["DENG"],
        anos=[2022, 2023],
        min_ufs=1,
    )
    assert result["uf_coverage"]["DENG"] == 12


def test_zero_rows_agravo_not_double_reported_by_uf_check():
    # DENG has zero rows entirely -- check 1 (presence) reports it; check 3
    # (UF coverage) must not additionally complain about DENG's UF coverage.
    counts = [("CHIK", 2022, 500), ("CHIK", 2023, 480)]
    conn = _mock_conn(counts, _full_uf_rows(["CHIK"]))
    with pytest.raises(AssertionError) as exc_info:
        m.assert_sinan_completeness(
            conn,
            allowlist=_empty_allowlist(),
            agravos=["DENG", "CHIK"],
            anos=[2022, 2023],
        )
    message = str(exc_info.value)
    assert "presence" in message
    assert "uf-coverage" not in message


def test_load_allowlist_parses_both_keys_uppercased_and_int_years(tmp_path):
    allowlist_path = tmp_path / "allowlist.yaml"
    allowlist_path.write_text(
        "known_absent:\n  - [deng, 2016]\nknown_partial:\n  - [ANIM, 2023]\n"
    )
    allowlist = m.load_allowlist(str(allowlist_path))
    assert allowlist["known_absent"] == {("DENG", 2016)}
    assert allowlist["known_partial"] == {("ANIM", 2023)}


def test_load_allowlist_missing_file_returns_two_empty_sets(tmp_path):
    missing_path = tmp_path / "does_not_exist.yaml"
    allowlist = m.load_allowlist(str(missing_path))
    assert allowlist["known_absent"] == set()
    assert allowlist["known_partial"] == set()


def test_grid_constants():
    assert m.ALL_AGRAVOS == ["DENG", "CHIK", "ANIM"]
    assert m.ALL_YEARS[0] == 2015
    assert m.ALL_YEARS[-1] == 2024
    assert m.ALL_UF_COUNT == 27
