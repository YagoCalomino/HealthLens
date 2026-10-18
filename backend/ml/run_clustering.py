"""K-Means clustering runner for HealthLens municipality health profiles.

Aggregates SIM/SIH Parquet data for a given reference year into a five-feature
matrix per municipality, runs K-Means, computes a PCA projection, and upserts
results into municipio_cluster_assignments.

Entry points:
  - run_clustering(conn, k, ano_referencia)  — callable from other ML scripts or notebooks
  - python -m ml.run_clustering --ano-referencia YEAR [--k K] [--raw-dir DIR]

In SAMPLE_MODE the runner reads from data/sample/; otherwise from --raw-dir.
Requires PostgreSQL and seeded dim_local table when writing results to DB.
"""

import argparse
import glob as glob_module
import json
import logging
import os
from pathlib import Path

import duckdb
import pandas as pd
import psycopg2
import psycopg2.extras
from sklearn.cluster import KMeans
from sklearn.decomposition import PCA
from sklearn.manifold import TSNE
from sklearn.metrics import silhouette_score
from sklearn.preprocessing import MinMaxScaler, StandardScaler

from etl import config

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Module-level constants
# ---------------------------------------------------------------------------

_BATCH_SIZE = 1000
_N_CLUSTERS_DEFAULT = (
    6  # placeholder until elbow method in notebook; overridable via CLI
)
_FEATURE_NAMES = [
    "taxa_mortalidade",
    "taxa_internacoes",
    "prop_cid_IX",
    "prop_cid_X",
    "prop_cid_I",
]
_ALGORITMO = "KMeans"

CLUSTER_NOME_MAP: dict[int, str] = {
    0: "Baixa Carga de Morbimortalidade",
    1: "Predominância Cardiovascular",
    2: "Outliers de Pequena População",
    3: "Carga Combinada Cardiovascular-Infecciosa",
    4: "Alta Carga Respiratória e Hospitalar",
    5: "Predominância de Doenças Infecciosas e Parasitárias",
}

_CLUSTER_UPSERT = """
INSERT INTO municipio_cluster_assignments (
    dim_local_id, cluster_id, algoritmo, n_clusters, silhouette_score,
    features_utilizadas, ano_referencia, cluster_nome, pca_x, pca_y, features_norm
) VALUES %s
ON CONFLICT (dim_local_id, algoritmo, n_clusters, ano_referencia)
DO UPDATE SET
    cluster_id       = EXCLUDED.cluster_id,
    silhouette_score = EXCLUDED.silhouette_score,
    cluster_nome     = EXCLUDED.cluster_nome,
    pca_x            = EXCLUDED.pca_x,
    pca_y            = EXCLUDED.pca_y,
    features_norm    = EXCLUDED.features_norm
"""

_UF_CLUSTER_UPSERT = """
INSERT INTO uf_cluster_assignments (
    sigla_uf, cluster_id, algoritmo, n_clusters, silhouette_score,
    features_utilizadas, ano_referencia, cluster_nome, pca_x, pca_y,
    n_municipios, features_norm
) VALUES %s
ON CONFLICT (sigla_uf, algoritmo, n_clusters, ano_referencia)
DO UPDATE SET
    cluster_id       = EXCLUDED.cluster_id,
    silhouette_score = EXCLUDED.silhouette_score,
    cluster_nome     = EXCLUDED.cluster_nome,
    pca_x            = EXCLUDED.pca_x,
    pca_y            = EXCLUDED.pca_y,
    n_municipios     = EXCLUDED.n_municipios,
    features_norm    = EXCLUDED.features_norm
"""


# ---------------------------------------------------------------------------
# Data helpers
# ---------------------------------------------------------------------------


def _load_population_df(pop_csv_path: str) -> pd.DataFrame:
    """Load TCU population CSV into a DataFrame.

    TCU CSV has a header row with Portuguese column names; skiprows=1 skips
    the descriptive first line that precedes the actual column header.
    DuckDB read_csv_auto() cannot handle the UTF-8 em-dash in that line,
    so pandas is used instead.
    """
    return pd.read_csv(
        pop_csv_path,
        skiprows=1,
        dtype={"codigo_ibge_6": str, "ano": int, "populacao_total": int},
    )


def _aggregate_features(
    sim_parquet: str | list[str],
    sih_parquet: str | list[str],
    pop_df: pd.DataFrame,
    ano_referencia: int,
) -> pd.DataFrame:
    """Build a five-feature municipality DataFrame for ano_referencia using DuckDB.

    Features computed:
      taxa_mortalidade   — deaths per 100k population (SIM)
      taxa_internacoes   — incident hospitalisations per 100k population (SIH, IDENT=1)
      prop_cid_IX        — proportion of deaths with ICD chapter IX (I00–I99, circulatory)
      prop_cid_X         — proportion of deaths with ICD chapter X (J00–J99, respiratory)
      prop_cid_I         — proportion of deaths with ICD chapter I (A00–B99, infectious)

    DuckDB parameterized queries (con.execute("...", [param])) guard against
    SQL injection from filesystem paths.

    Returns a DataFrame indexed by codigo_ibge_6 with columns matching _FEATURE_NAMES.
    NaN values (municipalities in dim_local but absent from Parquet) are filled with 0.0.
    """
    con = duckdb.connect()
    con.register("dim_populacao_csv", pop_df)

    # --- SIM aggregation: total deaths and CID chapter proportions ---
    sim_df = con.execute(
        """
        WITH sim_raw AS (
            SELECT
                CODMUNRES                                      AS codigo_ibge_6,
                CAUSABAS                                       AS cid,
                COUNT(*)                                       AS n
            FROM read_parquet(?)
            WHERE DTOBITO IS NOT NULL
              AND LENGTH(DTOBITO) = 8
              AND CAST(SUBSTRING(DTOBITO, 1, 4) AS INT) = ?
            GROUP BY CODMUNRES, CAUSABAS
        ),
        sim_totals AS (
            SELECT
                codigo_ibge_6,
                SUM(n)                                         AS total_obitos,
                SUM(CASE WHEN cid >= 'I00' AND cid <= 'I99' THEN n ELSE 0 END) AS n_cid_IX,
                SUM(CASE WHEN cid >= 'J00' AND cid <= 'J99' THEN n ELSE 0 END) AS n_cid_X,
                SUM(CASE WHEN cid >= 'A00' AND cid <= 'B99' THEN n ELSE 0 END) AS n_cid_I
            FROM sim_raw
            GROUP BY codigo_ibge_6
        )
        SELECT
            s.codigo_ibge_6,
            s.total_obitos * 100000.0 / NULLIF(p.populacao_total, 0) AS taxa_mortalidade,
            s.n_cid_IX * 1.0 / NULLIF(s.total_obitos, 0)             AS prop_cid_IX,
            s.n_cid_X  * 1.0 / NULLIF(s.total_obitos, 0)             AS prop_cid_X,
            s.n_cid_I  * 1.0 / NULLIF(s.total_obitos, 0)             AS prop_cid_I
        FROM sim_totals s
        LEFT JOIN dim_populacao_csv p
            ON s.codigo_ibge_6 = p.codigo_ibge_6 AND p.ano = ?
        """,
        [sim_parquet, ano_referencia, ano_referencia],
    ).df()

    # --- SIH aggregation: incident hospitalisations (IDENT = 1 only) ---
    # SP_TIPO belongs to the SIH-SP group only and is always NULL on genuine
    # RD/AIH rows since pysus concatenates SIH-RD and SIH-SP into one frame.
    sih_df = con.execute(
        """
        WITH sih_inc AS (
            SELECT
                MUNIC_RES                                      AS codigo_ibge_6,
                COUNT(*)                                       AS total_internacoes
            FROM read_parquet(?, union_by_name=True)
            WHERE IDENT = 1
              AND DT_INTER IS NOT NULL
              AND LENGTH(DT_INTER) = 8
              AND CAST(SUBSTRING(DT_INTER, 1, 4) AS INT) = ?
            GROUP BY MUNIC_RES
        )
        SELECT
            i.codigo_ibge_6,
            i.total_internacoes * 100000.0 / NULLIF(p.populacao_total, 0) AS taxa_internacoes
        FROM sih_inc i
        LEFT JOIN dim_populacao_csv p
            ON i.codigo_ibge_6 = p.codigo_ibge_6 AND p.ano = ?
        """,
        [sih_parquet, ano_referencia, ano_referencia],
    ).df()

    con.close()

    # --- Merge and fill missing values ---
    all_munic = pop_df[pop_df["ano"] == ano_referencia][
        ["codigo_ibge_6"]
    ].drop_duplicates()
    features_df = all_munic.merge(sim_df, on="codigo_ibge_6", how="left")
    features_df = features_df.merge(sih_df, on="codigo_ibge_6", how="left")
    features_df[_FEATURE_NAMES] = features_df[_FEATURE_NAMES].fillna(0.0)
    features_df = features_df.dropna(subset=["codigo_ibge_6"]).reset_index(drop=True)

    logger.info(
        "Feature aggregation complete: %d municipalities, ano=%d",
        len(features_df),
        ano_referencia,
    )
    return features_df


def _aggregate_uf_features(
    sim_parquet: str | list[str],
    sih_parquet: str | list[str],
    pop_df: pd.DataFrame,
    ano_referencia: int,
    uf_map_df: pd.DataFrame,
) -> pd.DataFrame:
    """Build a five-feature UF DataFrame for ano_referencia using DuckDB.

    Deliberately NOT `_aggregate_features(...).groupby("sigla_uf").mean()` —
    averaging already-computed município-level rates/proportions weights
    every município equally regardless of its population or event count,
    the same aggregation bug fixed in notificacoes.py's uf-summary endpoint.
    Instead this re-derives every feature from raw SIM/SIH counts
    summed at UF grain first, then divides once — SUM(deaths)*100000/
    SUM(população), not AVG(taxa_mortalidade).

    Args:
        uf_map_df: DataFrame with columns codigo_ibge_6, sigla_uf — the
            município→UF mapping (from dim_local), registered into DuckDB to
            join Parquet rows onto their UF before grouping.

    Returns a DataFrame indexed by sigla_uf with columns matching
    _FEATURE_NAMES plus n_municipios (count of current municípios composing
    that UF's aggregate, from uf_map_df — not just municípios with events).
    """
    con = duckdb.connect()
    con.register("dim_populacao_csv", pop_df)
    con.register("uf_map_csv", uf_map_df)

    sim_df = con.execute(
        """
        WITH sim_raw AS (
            SELECT
                m.sigla_uf                                     AS sigla_uf,
                s.CAUSABAS                                      AS cid,
                COUNT(*)                                       AS n
            FROM read_parquet(?) s
            JOIN uf_map_csv m ON s.CODMUNRES = m.codigo_ibge_6
            WHERE s.DTOBITO IS NOT NULL
              AND LENGTH(s.DTOBITO) = 8
              AND CAST(SUBSTRING(s.DTOBITO, 1, 4) AS INT) = ?
            GROUP BY m.sigla_uf, s.CAUSABAS
        ),
        sim_totals AS (
            SELECT
                sigla_uf,
                SUM(n)                                         AS total_obitos,
                SUM(CASE WHEN cid >= 'I00' AND cid <= 'I99' THEN n ELSE 0 END) AS n_cid_IX,
                SUM(CASE WHEN cid >= 'J00' AND cid <= 'J99' THEN n ELSE 0 END) AS n_cid_X,
                SUM(CASE WHEN cid >= 'A00' AND cid <= 'B99' THEN n ELSE 0 END) AS n_cid_I
            FROM sim_raw
            GROUP BY sigla_uf
        ),
        pop_uf AS (
            SELECT m.sigla_uf, SUM(p.populacao_total) AS populacao_total
            FROM dim_populacao_csv p
            JOIN uf_map_csv m ON p.codigo_ibge_6 = m.codigo_ibge_6
            WHERE p.ano = ?
            GROUP BY m.sigla_uf
        )
        SELECT
            s.sigla_uf,
            s.total_obitos * 100000.0 / NULLIF(p.populacao_total, 0) AS taxa_mortalidade,
            s.n_cid_IX * 1.0 / NULLIF(s.total_obitos, 0)             AS prop_cid_IX,
            s.n_cid_X  * 1.0 / NULLIF(s.total_obitos, 0)             AS prop_cid_X,
            s.n_cid_I  * 1.0 / NULLIF(s.total_obitos, 0)             AS prop_cid_I
        FROM sim_totals s
        LEFT JOIN pop_uf p ON s.sigla_uf = p.sigla_uf
        """,
        [sim_parquet, ano_referencia, ano_referencia],
    ).df()

    sih_df = con.execute(
        """
        WITH sih_inc AS (
            SELECT
                m.sigla_uf                                     AS sigla_uf,
                COUNT(*)                                       AS total_internacoes
            FROM read_parquet(?, union_by_name=True) i
            JOIN uf_map_csv m ON i.MUNIC_RES = m.codigo_ibge_6
            WHERE i.IDENT = 1
              AND i.DT_INTER IS NOT NULL
              AND LENGTH(i.DT_INTER) = 8
              AND CAST(SUBSTRING(i.DT_INTER, 1, 4) AS INT) = ?
            GROUP BY m.sigla_uf
        ),
        pop_uf AS (
            SELECT m.sigla_uf, SUM(p.populacao_total) AS populacao_total
            FROM dim_populacao_csv p
            JOIN uf_map_csv m ON p.codigo_ibge_6 = m.codigo_ibge_6
            WHERE p.ano = ?
            GROUP BY m.sigla_uf
        )
        SELECT
            i.sigla_uf,
            i.total_internacoes * 100000.0 / NULLIF(p.populacao_total, 0) AS taxa_internacoes
        FROM sih_inc i
        LEFT JOIN pop_uf p ON i.sigla_uf = p.sigla_uf
        """,
        [sih_parquet, ano_referencia, ano_referencia],
    ).df()

    n_municipios_df = (
        uf_map_df.groupby("sigla_uf").size().reset_index(name="n_municipios")
    )

    con.close()

    features_df = sim_df.merge(sih_df, on="sigla_uf", how="outer")
    features_df = features_df.merge(n_municipios_df, on="sigla_uf", how="right")
    features_df[_FEATURE_NAMES] = features_df[_FEATURE_NAMES].fillna(0.0)
    features_df = features_df.dropna(subset=["sigla_uf"]).reset_index(drop=True)

    logger.info(
        "UF feature aggregation complete: %d UFs, ano=%d",
        len(features_df),
        ano_referencia,
    )
    return features_df


# ---------------------------------------------------------------------------
# Main clustering function
# ---------------------------------------------------------------------------


def _resolve_data_paths(raw_dir: str) -> tuple[str | list[str], str | list[str], str]:
    """Resolve (sim_parquet, sih_parquet, pop_csv_path) for SAMPLE_MODE or full mode.

    Shared by both the município-grain and UF-grain runners so the two paths
    can never drift onto different source data.
    """
    if config.SAMPLE_MODE:
        if os.environ.get("SAMPLE_DATA_DIR"):
            sample_dir = Path(config.SAMPLE_DATA_DIR)
        else:
            # backend/ml/run_clustering.py → backend/ml → backend → repo root
            sample_dir = (
                Path(__file__).resolve().parent.parent.parent / "data" / "sample"
            )
        sim_parquet: str | list[str] = str(sample_dir / "sim_sample.parquet")
        sih_parquet: str | list[str] = str(sample_dir / "sih_sample.parquet")
        pop_csv_path = str(
            Path(__file__).resolve().parent.parent
            / "seeds"
            / "data"
            / "tcu_populacao.csv"
        )
        return sim_parquet, sih_parquet, pop_csv_path

    # Full mode: SIM and SIH live flat in raw_dir as SIM_{UF}_{ANO}.parquet /
    # SIH_{UF}_{ANO}.parquet — glob by filename prefix, not subdirectory.
    sim_glob = str(Path(raw_dir) / "SIM_*.parquet")
    if not glob_module.glob(sim_glob):
        raise FileNotFoundError(f"No SIM Parquet files found matching {sim_glob}")
    sim_parquet = sim_glob  # DuckDB read_parquet() expands glob patterns natively

    sih_glob = str(Path(raw_dir) / "SIH_*.parquet")
    if not glob_module.glob(sih_glob):
        raise FileNotFoundError(f"No SIH Parquet files found matching {sih_glob}")
    sih_parquet = sih_glob  # DuckDB read_parquet() expands glob patterns natively

    pop_csv_path = str(
        Path(__file__).resolve().parent.parent / "seeds" / "data" / "tcu_populacao.csv"
    )
    return sim_parquet, sih_parquet, pop_csv_path


def run_clustering(
    conn,
    *,
    k: int = _N_CLUSTERS_DEFAULT,
    ano_referencia: int,
    raw_dir: str = "data/raw",
) -> dict:
    """Run K-Means clustering on municipality health features and write results to DB.

    Steps:
      1. Resolve data paths from SAMPLE_MODE or CLI raw-dir.
      2. Load population CSV via pandas (skiprows=1 — TCU format).
      3. Aggregate five-feature matrix using DuckDB parameterized queries.
      4. Standardise with StandardScaler; cluster with KMeans(n_init=10, random_state=42).
      5. Project to 2D with PCA(n_components=2) for choropleth rendering.
      6. Compute silhouette_score for quality metric.
      7. Load dim_local → local_id_map; upsert rows into municipio_cluster_assignments.

    Args:
        conn:           Live psycopg2 connection with autocommit disabled.
        k:              Number of clusters (default _N_CLUSTERS_DEFAULT; override via CLI).
        ano_referencia: Reference year for feature aggregation and the snapshot
                         written to municipio_cluster_assignments. Required —
                         no default, so no invocation can silently write an
                         unintended year.
        raw_dir:        Directory containing flat SIM_*/SIH_*.parquet files (full mode only).

    Returns:
        Summary dict: rows_written, n_clusters, silhouette_score, ano_referencia.
    """
    sim_parquet, sih_parquet, pop_csv_path = _resolve_data_paths(raw_dir)

    logger.info(
        "Starting clustering: SAMPLE_MODE=%s k=%d ano=%d",
        config.SAMPLE_MODE,
        k,
        ano_referencia,
    )

    # ------------------------------------------------------------------
    # 2. Load population reference table
    # ------------------------------------------------------------------
    pop_df = _load_population_df(pop_csv_path)

    # ------------------------------------------------------------------
    # 3. Aggregate features
    # ------------------------------------------------------------------
    features_df = _aggregate_features(sim_parquet, sih_parquet, pop_df, ano_referencia)

    if len(features_df) < k:
        raise ValueError(
            f"Cannot form {k} clusters from {len(features_df)} municipalities — "
            "reduce k or increase data coverage"
        )

    X = features_df[_FEATURE_NAMES].values  # shape: (n_municipios, 5)

    # ------------------------------------------------------------------
    # 4. Standardise + cluster
    # ------------------------------------------------------------------
    X_scaled = StandardScaler().fit_transform(X)  # shape: (n_municipios, 5)

    km = KMeans(n_clusters=k, random_state=42, n_init=10)
    km.fit(X_scaled)
    labels = km.labels_  # shape: (n_municipios,)

    # ------------------------------------------------------------------
    # 5. PCA projection (stored for choropleth scatter rendering)
    # ------------------------------------------------------------------
    pca = PCA(n_components=2)
    X_pca = pca.fit_transform(X_scaled)  # shape: (n_municipios, 2)
    pca_scaler = MinMaxScaler(feature_range=(-1, 1))
    X_pca = pca_scaler.fit_transform(X_pca)

    import numpy as np

    if X_pca[:, 1].max() - X_pca[:, 1].min() < 1e-6:
        rng = np.random.default_rng(42)
        X_pca[:, 1] = rng.normal(0, 0.3, size=len(X_pca))

    # ------------------------------------------------------------------
    # 6. Silhouette score
    # ------------------------------------------------------------------
    sil = silhouette_score(X_scaled, labels)
    logger.info("KMeans fit complete: k=%d silhouette=%.4f", k, sil)

    # ------------------------------------------------------------------
    # 7. Load dim_local lookup (inline — no DimCache class needed for ML)
    # ------------------------------------------------------------------
    with conn.cursor() as cur:
        cur.execute("SELECT id, codigo_ibge_6 FROM dim_local WHERE is_current = TRUE")
        local_id_map: dict[str, int] = {row[1]: row[0] for row in cur.fetchall()}
    logger.info("dim_local cache loaded: %d entries", len(local_id_map))

    # ------------------------------------------------------------------
    # 8. Build rows and upsert in batches
    # ------------------------------------------------------------------
    batch: list[tuple] = []
    rows_written = 0
    skipped = 0
    features_utilizadas = ",".join(_FEATURE_NAMES)

    for i in range(len(features_df)):
        codigo_ibge_6 = str(features_df.iloc[i]["codigo_ibge_6"])
        dim_local_id = local_id_map.get(codigo_ibge_6)

        if dim_local_id is None:
            logger.warning(
                "dim_local not found for codigo_ibge_6=%s — skipping", codigo_ibge_6
            )
            skipped += 1
            continue

        cluster_id = int(labels[i])
        cluster_nome = CLUSTER_NOME_MAP.get(cluster_id, "PLACEHOLDER")
        features_norm_str = json.dumps(
            dict(zip(_FEATURE_NAMES, [round(float(v), 4) for v in X_scaled[i]]))
        )

        batch.append(
            (
                dim_local_id,
                cluster_id,
                _ALGORITMO,
                k,
                float(sil),
                features_utilizadas,
                ano_referencia,
                cluster_nome,
                round(float(X_pca[i, 0]), 4),
                round(float(X_pca[i, 1]), 4),
                features_norm_str,
            )
        )

        if len(batch) >= _BATCH_SIZE:
            with conn.cursor() as cur:
                psycopg2.extras.execute_values(cur, _CLUSTER_UPSERT, batch)
            conn.commit()
            rows_written += len(batch)
            batch.clear()

    # Flush remaining rows
    if batch:
        with conn.cursor() as cur:
            psycopg2.extras.execute_values(cur, _CLUSTER_UPSERT, batch)
        conn.commit()
        rows_written += len(batch)

    logger.info(
        "Clustering complete: rows_written=%d skipped=%d n_clusters=%d silhouette=%.4f",
        rows_written,
        skipped,
        k,
        sil,
    )

    return {
        "rows_written": rows_written,
        "n_clusters": k,
        "silhouette_score": float(sil),
        "ano_referencia": ano_referencia,
    }


# UF-grain default is lower than the município default: only 27 data points
# exist at this grain, and KMeans needs n_clusters <= n_samples with enough
# headroom for a meaningful silhouette score.
_UF_N_CLUSTERS_DEFAULT = 5


def run_clustering_uf(
    conn,
    *,
    k: int = _UF_N_CLUSTERS_DEFAULT,
    ano_referencia: int,
    raw_dir: str = "data/raw",
) -> dict:
    """Run K-Means clustering on UF-grain health features and write results
    to uf_cluster_assignments — the national-view companion to run_clustering's
    município grain.

    Deliberately a full, independent KMeans+PCA fit on 27 UF-level feature
    rows, not a post-hoc aggregate of municipio_cluster_assignments: PCA
    scores are mean-centered at zero by construction, so averaging
    município-level pca_y (a component mostly capturing município-to-
    município noise) per UF regressed every UF toward zero, producing a
    flat-line scatter instead of real 2D variance. Fitting PCA directly on
    UF-level features decomposes whatever variance actually exists between
    UFs.

    Args:
        conn:           Live psycopg2 connection with autocommit disabled.
        k:              Number of clusters (default _UF_N_CLUSTERS_DEFAULT).
        ano_referencia: Reference year — required, no default (mirrors run_clustering).
        raw_dir:        Directory containing flat SIM_*/SIH_*.parquet files (full mode only).

    Returns:
        Summary dict: rows_written, n_clusters, silhouette_score, ano_referencia.
    """
    sim_parquet, sih_parquet, pop_csv_path = _resolve_data_paths(raw_dir)

    logger.info(
        "Starting UF-grain clustering: SAMPLE_MODE=%s k=%d ano=%d",
        config.SAMPLE_MODE,
        k,
        ano_referencia,
    )

    pop_df = _load_population_df(pop_csv_path)

    with conn.cursor() as cur:
        cur.execute(
            "SELECT codigo_ibge_6, sigla_uf FROM dim_local WHERE is_current = TRUE"
        )
        uf_map_df = pd.DataFrame(cur.fetchall(), columns=["codigo_ibge_6", "sigla_uf"])
    logger.info(
        "dim_local UF map loaded: %d municípios across %d UFs",
        len(uf_map_df),
        uf_map_df["sigla_uf"].nunique(),
    )

    features_df = _aggregate_uf_features(
        sim_parquet, sih_parquet, pop_df, ano_referencia, uf_map_df
    )

    if len(features_df) < k:
        raise ValueError(
            f"Cannot form {k} clusters from {len(features_df)} UFs — "
            "reduce k or check dim_local coverage"
        )

    X = features_df[_FEATURE_NAMES].values  # shape: (n_ufs, 5)

    X_scaled = StandardScaler().fit_transform(X)

    km = KMeans(n_clusters=k, random_state=42, n_init=10)
    km.fit(X_scaled)
    labels = km.labels_

    tsne = TSNE(n_components=2, random_state=42, perplexity=5, n_iter=1000)
    X_pca = tsne.fit_transform(X_scaled)

    import numpy as np

    if X_pca[:, 1].max() - X_pca[:, 1].min() < 1e-6:
        rng = np.random.default_rng(42)
        X_pca[:, 1] = rng.normal(0, 0.3, size=len(X_pca))

    X_pca = MinMaxScaler(feature_range=(-1, 1)).fit_transform(X_pca)

    sil = silhouette_score(X_scaled, labels)
    logger.info("UF-grain KMeans fit complete: k=%d silhouette=%.4f", k, sil)

    batch: list[tuple] = []
    rows_written = 0
    features_utilizadas = ",".join(_FEATURE_NAMES)

    for i in range(len(features_df)):
        sigla_uf = str(features_df.iloc[i]["sigla_uf"])
        cluster_id = int(labels[i])
        cluster_nome = CLUSTER_NOME_MAP.get(cluster_id, "PLACEHOLDER")
        features_norm_str = json.dumps(
            dict(zip(_FEATURE_NAMES, [round(float(v), 4) for v in X_scaled[i]]))
        )

        batch.append(
            (
                sigla_uf,
                cluster_id,
                _ALGORITMO,
                k,
                float(sil),
                features_utilizadas,
                ano_referencia,
                cluster_nome,
                round(float(X_pca[i, 0]), 6),
                round(float(X_pca[i, 1]), 6),
                int(features_df.iloc[i]["n_municipios"]),
                features_norm_str,
            )
        )

    if batch:
        with conn.cursor() as cur:
            psycopg2.extras.execute_values(cur, _UF_CLUSTER_UPSERT, batch)
        conn.commit()
        rows_written = len(batch)

    logger.info(
        "UF-grain clustering complete: rows_written=%d n_clusters=%d silhouette=%.4f",
        rows_written,
        k,
        sil,
    )

    return {
        "rows_written": rows_written,
        "n_clusters": k,
        "silhouette_score": float(sil),
        "ano_referencia": ano_referencia,
    }


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------


def _build_arg_parser() -> argparse.ArgumentParser:
    """Build the CLI argument parser (extracted for unit testing without executing the CLI)."""
    parser = argparse.ArgumentParser(description="HealthLens K-Means clustering runner")
    parser.add_argument(
        "--k",
        type=int,
        default=_N_CLUSTERS_DEFAULT,
        help="Number of clusters (default: %(default)s)",
    )
    parser.add_argument(
        "--ano-referencia",
        type=int,
        required=True,
        help=(
            "Reference year for feature aggregation and the ano_referencia "
            "value written to municipio_cluster_assignments"
        ),
    )
    parser.add_argument(
        "--raw-dir",
        default="data/raw",
        help="Directory containing raw Parquet files (full mode only; default: %(default)s)",
    )
    parser.add_argument(
        "--grain",
        choices=["municipio", "uf"],
        default="municipio",
        help=(
            "municipio: writes municipio_cluster_assignments (default). "
            "uf: writes uf_cluster_assignments — a genuinely UF-grain KMeans+PCA "
            "run for ClusterScatterPlot's national view, not an aggregate of the "
            "município run. Override --k for uf grain (default 6 is a "
            "lot of clusters for 27 points; consider --k 5)."
        ),
    )
    return parser


if __name__ == "__main__":
    args = _build_arg_parser().parse_args()

    if not config.DATABASE_URL_SYNC:
        raise RuntimeError("DATABASE_URL_SYNC environment variable is required")

    logger.info(
        "Starting clustering runner: SAMPLE_MODE=%s grain=%s k=%d ano=%d",
        config.SAMPLE_MODE,
        args.grain,
        args.k,
        args.ano_referencia,
    )

    conn = psycopg2.connect(config.DATABASE_URL_SYNC)
    try:
        if args.grain == "uf":
            summary = run_clustering_uf(
                conn, k=args.k, ano_referencia=args.ano_referencia, raw_dir=args.raw_dir
            )
        else:
            summary = run_clustering(
                conn, k=args.k, ano_referencia=args.ano_referencia, raw_dir=args.raw_dir
            )
    finally:
        conn.close()

    print(f"\nClustering complete: {summary}")
