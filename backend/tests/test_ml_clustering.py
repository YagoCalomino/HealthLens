"""Unit tests for ML clustering runner.

All tests are pure Python — no database required.
Run with:
    cd backend && SAMPLE_MODE=true pytest tests/test_ml_clustering.py -v
"""

import json

import numpy as np
import pandas as pd
import pytest
from sklearn.cluster import KMeans
from sklearn.decomposition import PCA

import ml.run_clustering
from ml.run_clustering import _aggregate_features, _build_arg_parser

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_N_MUNICIPIOS = 20


def _make_feature_matrix(n: int = _N_MUNICIPIOS, n_features: int = 5) -> np.ndarray:
    """Return a synthetic feature matrix of shape (n, n_features) for clustering tests."""
    rng = np.random.default_rng(42)
    return rng.uniform(0, 100, size=(n, n_features)).astype(np.float64)


# ---------------------------------------------------------------------------
# Clustering tests
# ---------------------------------------------------------------------------


def test_kmeans_labels_shape():
    """KMeans produces labels array of shape (n_samples,) with the expected cluster count."""
    X = _make_feature_matrix()
    km = KMeans(n_clusters=3, random_state=42, n_init=10)
    km.fit(X)
    assert km.labels_.shape == (X.shape[0],)
    assert len(set(km.labels_)) == 3


def test_features_norm_json_serializes_correctly():
    """features_norm serializes to a valid JSON string with correct keys and values."""
    feature_names = [
        "taxa_mortalidade",
        "taxa_internacoes",
        "prop_cid_IX",
        "prop_cid_X",
        "prop_cid_I",
    ]
    row = np.array([0.42, 0.31, 0.18, 0.15, 0.12])
    result = json.dumps(dict(zip(feature_names, [round(float(v), 4) for v in row])))
    parsed = json.loads(result)
    assert set(parsed.keys()) == set(feature_names)
    assert abs(parsed["taxa_mortalidade"] - 0.42) < 1e-4


def test_pca_components_shape():
    """PCA with n_components=2 produces a projection of shape (n_samples, 2)."""
    X = _make_feature_matrix()
    pca = PCA(n_components=2)
    X_pca = pca.fit_transform(X)
    assert X_pca.shape == (20, 2)


# ---------------------------------------------------------------------------
# ano_referencia threading + CLI contract regression tests
# ---------------------------------------------------------------------------


def test_aggregate_features_respects_ano_referencia(tmp_path):
    """_aggregate_features filters strictly by the given ano_referencia — not a hardcoded year."""
    municipio = "355030"

    sim_df = pd.DataFrame(
        {
            "CODMUNRES": [municipio] * 3 + [municipio] * 7,
            "CAUSABAS": ["I219"] * 3 + ["J189"] * 7,
            "DTOBITO": ["20210115"] * 3 + ["20230115"] * 7,
        }
    )
    sim_path = tmp_path / "sim.parquet"
    sim_df.to_parquet(sim_path)

    sih_df = pd.DataFrame(
        {
            "MUNIC_RES": [municipio] * 2 + [municipio] * 4,
            "IDENT": [1] * 2 + [1] * 4,
            "DT_INTER": ["20210210"] * 2 + ["20230210"] * 4,
        }
    )
    sih_path = tmp_path / "sih.parquet"
    sih_df.to_parquet(sih_path)

    pop_df = pd.DataFrame(
        {
            "codigo_ibge_6": [municipio, municipio],
            "ano": [2021, 2023],
            "populacao_total": [100_000, 100_000],
        }
    )

    features_2021 = _aggregate_features(
        str(sim_path), str(sih_path), pop_df, ano_referencia=2021
    )
    features_2023 = _aggregate_features(
        str(sim_path), str(sih_path), pop_df, ano_referencia=2023
    )

    row_2021 = features_2021.loc[features_2021["codigo_ibge_6"] == municipio].iloc[0]
    row_2023 = features_2023.loc[features_2023["codigo_ibge_6"] == municipio].iloc[0]

    # 3 deaths / 100k pop vs 7 deaths / 100k pop — proves the year genuinely filters.
    assert row_2021["taxa_mortalidade"] == pytest.approx(3.0)
    assert row_2023["taxa_mortalidade"] == pytest.approx(7.0)
    assert row_2021["taxa_mortalidade"] != row_2023["taxa_mortalidade"]


def test_arg_parser_requires_ano_referencia():
    """--ano-referencia is required with no default; omitting it raises SystemExit."""
    parser = _build_arg_parser()

    with pytest.raises(SystemExit):
        parser.parse_args([])

    args = parser.parse_args(["--ano-referencia", "2021"])
    assert args.ano_referencia == 2021
    assert args.k == 6
    assert args.raw_dir == "data/raw"


def test_module_has_no_hardcoded_ano_referencia_constant():
    """Guard against a silent regression back to a module-level 2023 constant."""
    assert not hasattr(ml.run_clustering, "_ANO_REFERENCIA")


def test_aggregate_features_handles_mixed_schema_sih_parquet(tmp_path):
    """SIH glob covering old SP-schema and new RD-schema files must not raise a
    DuckDB schema-mismatch error — read_parquet(..., union_by_name=True) matches
    columns by name so files with different column sets/counts coexist in one glob.

    The old SP-schema file has no IDENT column at all (union_by_name fills it
    with NULL), so its rows are correctly excluded by WHERE IDENT = 1 — only
    genuine RD/AIH rows from the new-schema file are counted.
    """
    municipio = "355030"

    sim_df = pd.DataFrame(
        {
            "CODMUNRES": [municipio],
            "CAUSABAS": ["I219"],
            "DTOBITO": ["20210115"],
        }
    )
    sim_path = tmp_path / "sim.parquet"
    sim_df.to_parquet(sim_path)

    # Old SP-schema file: fewer columns, no IDENT — SP_TIPO is always NULL on
    # real RD/AIH rows, so this schema must not contribute to the count.
    sih_old_df = pd.DataFrame(
        {
            "MUNIC_RES": [municipio, municipio],
            "SP_TIPO": [1, 1],
            "DT_INTER": ["20210210", "20210211"],
        }
    )
    sih_old_path = tmp_path / "SIH_SP_2021.parquet"
    sih_old_df.to_parquet(sih_old_path)

    # New RD-schema file: has IDENT, the real incident-AIH discriminator.
    sih_new_df = pd.DataFrame(
        {
            "MUNIC_RES": [municipio],
            "SP_TIPO": [1],
            "DT_INTER": ["20210212"],
            "IDENT": [1],
        }
    )
    sih_new_path = tmp_path / "SIH_RD_2021.parquet"
    sih_new_df.to_parquet(sih_new_path)

    sih_glob = str(tmp_path / "SIH_*.parquet")

    pop_df = pd.DataFrame(
        {
            "codigo_ibge_6": [municipio],
            "ano": [2021],
            "populacao_total": [100_000],
        }
    )

    features = _aggregate_features(str(sim_path), sih_glob, pop_df, ano_referencia=2021)

    row = features.loc[features["codigo_ibge_6"] == municipio].iloc[0]
    # Only the 1 new-schema (IDENT=1) row counts / 100k pop; the 2 old-schema
    # rows have no IDENT column and are correctly excluded.
    assert row["taxa_internacoes"] == pytest.approx(1.0)


# ---------------------------------------------------------------------------
# UF-grain aggregation
# ---------------------------------------------------------------------------


def test_aggregate_uf_features_sums_raw_counts_not_average_of_rates(tmp_path):
    """Regression: UF-level taxa_mortalidade must be
    SUM(obitos) * 100000 / SUM(populacao) across the UF's municípios, never
    the average of each município's already-computed rate — the same
    aggregation bug fixed in notificacoes.py's uf-summary endpoint.
    Two SP municípios with very different populations (10k vs
    1M) each get some deaths; naively averaging their individual rates would
    weight the tiny município equally with the large one.
    """
    from ml.run_clustering import _aggregate_uf_features

    small_muni, large_muni = "355900", "355901"

    sim_df = pd.DataFrame(
        {
            "CODMUNRES": [small_muni] * 2 + [large_muni] * 20,
            "CAUSABAS": ["I219"] * 2 + ["J189"] * 20,
            "DTOBITO": ["20230115"] * 22,
        }
    )
    sim_path = tmp_path / "sim.parquet"
    sim_df.to_parquet(sim_path)

    sih_df = pd.DataFrame(
        {
            "MUNIC_RES": pd.Series([], dtype="str"),
            "IDENT": pd.Series([], dtype="int"),
            "DT_INTER": pd.Series([], dtype="str"),
        }
    )
    sih_path = tmp_path / "sih.parquet"
    sih_df.to_parquet(sih_path)

    pop_df = pd.DataFrame(
        {
            "codigo_ibge_6": [small_muni, large_muni],
            "ano": [2023, 2023],
            "populacao_total": [10_000, 1_000_000],
        }
    )

    uf_map_df = pd.DataFrame(
        {"codigo_ibge_6": [small_muni, large_muni], "sigla_uf": ["SP", "SP"]}
    )

    features = _aggregate_uf_features(
        str(sim_path), str(sih_path), pop_df, ano_referencia=2023, uf_map_df=uf_map_df
    )

    assert len(features) == 1
    row = features.iloc[0]
    assert row["sigla_uf"] == "SP"
    assert row["n_municipios"] == 2

    naive_average = (2 / 10_000 * 100_000 + 20 / 1_000_000 * 100_000) / 2  # 12.0
    correct_rate = 22 * 100_000.0 / (10_000 + 1_000_000)  # ~2.178

    assert row["taxa_mortalidade"] == pytest.approx(correct_rate, abs=1e-3)
    assert row["taxa_mortalidade"] < naive_average / 2, (
        "taxa_mortalidade looks like an average of per-município rates, not "
        "SUM(obitos)*100000/SUM(populacao)"
    )


def test_aggregate_uf_features_n_municipios_counts_all_current_municipios(tmp_path):
    """n_municipios reflects every current município mapped to the UF (from
    dim_local via uf_map_df), including ones with zero events that year —
    not just municípios that happen to appear in the SIM/SIH Parquet."""
    from ml.run_clustering import _aggregate_uf_features

    active_muni, silent_muni = "355900", "355901"

    sim_df = pd.DataFrame(
        {"CODMUNRES": [active_muni], "CAUSABAS": ["I219"], "DTOBITO": ["20230115"]}
    )
    sim_path = tmp_path / "sim.parquet"
    sim_df.to_parquet(sim_path)

    sih_df = pd.DataFrame(
        {
            "MUNIC_RES": pd.Series([], dtype="str"),
            "IDENT": pd.Series([], dtype="int"),
            "DT_INTER": pd.Series([], dtype="str"),
        }
    )
    sih_path = tmp_path / "sih.parquet"
    sih_df.to_parquet(sih_path)

    pop_df = pd.DataFrame(
        {
            "codigo_ibge_6": [active_muni, silent_muni],
            "ano": [2023, 2023],
            "populacao_total": [50_000, 20_000],
        }
    )

    uf_map_df = pd.DataFrame(
        {"codigo_ibge_6": [active_muni, silent_muni], "sigla_uf": ["SP", "SP"]}
    )

    features = _aggregate_uf_features(
        str(sim_path), str(sih_path), pop_df, ano_referencia=2023, uf_map_df=uf_map_df
    )

    assert len(features) == 1
    assert features.iloc[0]["n_municipios"] == 2
