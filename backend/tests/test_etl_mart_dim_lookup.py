"""Unit tests for DimCache pure lookup methods.

All tests are pure-Python — no database required. DimCache's lookup dicts
are populated by hand (bypassing load_all(), which needs a live conn) so
get_causa_id / get_faixa_etaria_id / get_populacao / get_local_id can be
exercised in isolation, including their fallback branches.

Run with:
    cd backend && SAMPLE_MODE=true pytest tests/test_etl_mart_dim_lookup.py -v
"""

from etl.mart.dim_lookup import DimCache


def _make_cache() -> DimCache:
    cache = DimCache()
    cache.causa = {
        "I219": 1,
        "I21": 2,  # 3-char prefix alias, distinct id from full code below
        "J1": 3,  # 2-char prefix alias
    }
    cache.faixa_etaria = {
        "0_4": 10,
        "5_14": 11,
        "ignorada": 99,
    }
    cache.populacao = {
        ("355030", 2022): 12_396_372,
    }
    cache.local = {
        "355030": 500,
    }
    cache.agravo = {"DENG": 1, "CHIK": 2, "ANIM": 3}
    return cache


# ---------------------------------------------------------------------------
# get_causa_id
# ---------------------------------------------------------------------------


def test_get_causa_id_exact_match():
    """Exact normalised CID-10 code hit returns its own id."""
    cache = _make_cache()
    assert cache.get_causa_id("I219") == 1


def test_get_causa_id_prefix_fallback():
    """Unknown full code falls back to the 3-char CID-10 prefix."""
    cache = _make_cache()
    # "I2199" has no exact match but its 3-char prefix "I21" is aliased.
    assert cache.get_causa_id("I2199") == 2


def test_get_causa_id_no_match_returns_none():
    """No exact, 3-char, or 2-char prefix match returns None."""
    cache = _make_cache()
    assert cache.get_causa_id("Z999") is None


def test_get_causa_id_normalises_case_and_whitespace():
    """Lower-case / padded input is normalised before lookup."""
    cache = _make_cache()
    assert cache.get_causa_id(" i219 ") == 1


# ---------------------------------------------------------------------------
# get_faixa_etaria_id
# ---------------------------------------------------------------------------


def test_get_faixa_etaria_id_known_code():
    """Known faixa-etaria code returns its id directly."""
    cache = _make_cache()
    assert cache.get_faixa_etaria_id("0_4") == 10


def test_get_faixa_etaria_id_unknown_falls_back_to_ignorada():
    """Unrecognised code falls back to the 'ignorada' bucket."""
    cache = _make_cache()
    assert cache.get_faixa_etaria_id("nonexistent_bucket") == 99


def test_get_faixa_etaria_id_missing_ignorada_returns_none():
    """If 'ignorada' itself was never seeded, fallback resolves to None."""
    cache = DimCache()
    cache.faixa_etaria = {"0_4": 10}
    assert cache.get_faixa_etaria_id("unknown") is None


# ---------------------------------------------------------------------------
# get_populacao
# ---------------------------------------------------------------------------


def test_get_populacao_present():
    """(codigo_ibge_6, ano) present in the dict returns its value."""
    cache = _make_cache()
    assert cache.get_populacao("355030", 2022) == 12_396_372


def test_get_populacao_absent_returns_none():
    """Missing municipality x year combination returns None."""
    cache = _make_cache()
    assert cache.get_populacao("355030", 1999) is None
    assert cache.get_populacao("000000", 2022) is None


# ---------------------------------------------------------------------------
# get_local_id
# ---------------------------------------------------------------------------


def test_get_local_id_known_code():
    """Known codigo_ibge_6 returns its dim_local id."""
    cache = _make_cache()
    assert cache.get_local_id("355030") == 500


def test_get_local_id_absent_returns_none():
    """Codigo_ibge_6 not present in dim_local returns None."""
    cache = _make_cache()
    assert cache.get_local_id("000000") is None


# ---------------------------------------------------------------------------
# get_agravo_id
# ---------------------------------------------------------------------------


def test_get_agravo_id_known_code():
    """Known dim_agravo code returns its id directly."""
    cache = _make_cache()
    assert cache.get_agravo_id("DENG") == 1


def test_get_agravo_id_normalises_case():
    """Lower-case input is normalised to uppercase before lookup."""
    cache = _make_cache()
    assert cache.get_agravo_id("deng") == 1


def test_get_agravo_id_unknown_returns_none_and_warns(caplog):
    """Unrecognised code returns None and logs a warning — no fallback bucket."""
    cache = _make_cache()
    with caplog.at_level("WARNING"):
        result = cache.get_agravo_id("ZIKA")
    assert result is None
    assert "dim_agravo not found" in caplog.text


def test_get_agravo_id_empty_string_returns_none():
    """Empty string returns None without raising."""
    cache = _make_cache()
    assert cache.get_agravo_id("") is None


def test_get_agravo_id_none_returns_none():
    """None returns None without raising."""
    cache = _make_cache()
    assert cache.get_agravo_id(None) is None
