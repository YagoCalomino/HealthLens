import asyncio
import datetime

import pytest


def test_clusters_sample_mode_503(client):
    response = client.get("/clusters")
    assert response.status_code == 503


def test_openapi_schema_clusters(client):
    response = client.get("/openapi.json")
    assert response.status_code == 200
    paths = response.json()["paths"]
    # FastAPI registers prefix="/clusters" + get("/") as "/clusters/" in OpenAPI schema.
    # Check for either form to be robust across FastAPI trailing-slash handling.
    assert any(p.startswith("/clusters") for p in paths)


@pytest.fixture
def _clusters_db_harness(monkeypatch):
    """Isolated in-memory SQLite override for DB-backed clusters router coverage.

    Mirrors the harness in test_routers_indicadores.py — router module import
    (not fresh `from app.config import ...`) to avoid the stale-singleton
    caveat documented there.
    """
    from sqlalchemy import MetaData, insert
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
    from sqlalchemy.pool import StaticPool

    from app.main import app
    from app.models.dimensions import DimLocal
    from app.models.ml_results import MunicipioClusterAssignments as MCA
    from app.models.ml_results import UfClusterAssignments as UCA
    from app.routers import clusters as clusters_module

    settings = clusters_module.settings
    get_db = clusters_module.get_db

    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    orm_metadata = MetaData()
    DimLocal.__table__.to_metadata(orm_metadata)
    MCA.__table__.to_metadata(orm_metadata)
    UCA.__table__.to_metadata(orm_metadata)

    async def _setup():
        async with engine.begin() as conn:
            await conn.run_sync(orm_metadata.create_all)

    asyncio.run(_setup())

    async def _override_get_db():
        async with session_factory() as session:
            yield session

    monkeypatch.setattr(settings, "sample_mode", False)
    app.dependency_overrides[get_db] = _override_get_db

    yield {
        "engine": engine,
        "session_factory": session_factory,
        "insert": insert,
        "DimLocal": DimLocal,
        "MCA": MCA,
        "UCA": UCA,
        "app": app,
        "get_db": get_db,
    }

    app.dependency_overrides.pop(get_db, None)
    asyncio.run(engine.dispose())


def _seed_clusters(h):
    DimLocal = h["DimLocal"]
    MCA = h["MCA"]
    insert = h["insert"]

    async def _seed():
        async with h["session_factory"]() as session:
            await session.execute(
                insert(DimLocal),
                [
                    {
                        "codigo_ibge_6": "355030",
                        "codigo_ibge_7": "3550308",
                        "nome_municipio": "Sao Paulo",
                        "nome_uf": "Sao Paulo",
                        "sigla_uf": "SP",
                        "codigo_uf": "35",
                        "regiao": "Sudeste",
                        "valid_from": datetime.date(2020, 1, 1),
                        "is_current": True,
                        "ativo": True,
                    },
                    {
                        "codigo_ibge_6": "330455",
                        "codigo_ibge_7": "3304557",
                        "nome_municipio": "Rio de Janeiro",
                        "nome_uf": "Rio de Janeiro",
                        "sigla_uf": "RJ",
                        "codigo_uf": "33",
                        "regiao": "Sudeste",
                        "valid_from": datetime.date(2020, 1, 1),
                        "is_current": True,
                        "ativo": True,
                    },
                ],
            )
            await session.commit()
            result = await session.execute(DimLocal.__table__.select())
            rows = {row.sigla_uf: row.id for row in result.all()}

            await session.execute(
                insert(MCA),
                [
                    {
                        "dim_local_id": rows["SP"],
                        "cluster_id": 1,
                        "algoritmo": "KMeans",
                        "n_clusters": 3,
                        "silhouette_score": 0.6,
                        "features_utilizadas": '["taxa_mortalidade_100k"]',
                        "ano_referencia": 2023,
                        "cluster_nome": "Alto risco",
                        "pca_x": 1.0,
                        "pca_y": 2.0,
                        "features_norm": {"taxa_mortalidade_100k": 0.8},
                    },
                    {
                        "dim_local_id": rows["RJ"],
                        "cluster_id": 2,
                        "algoritmo": "KMeans",
                        "n_clusters": 3,
                        "silhouette_score": 0.5,
                        "features_utilizadas": '["taxa_mortalidade_100k"]',
                        "ano_referencia": 2023,
                        "cluster_nome": "Baixo risco",
                        "pca_x": -1.0,
                        "pca_y": -2.0,
                        "features_norm": {"taxa_mortalidade_100k": 0.2},
                    },
                ],
            )
            await session.commit()

    asyncio.run(_seed())


def test_clusters_returns_200_with_seeded_rows(_clusters_db_harness):
    from fastapi.testclient import TestClient

    h = _clusters_db_harness
    _seed_clusters(h)

    with TestClient(h["app"]) as local_client:
        response = local_client.get("/clusters")

    assert response.status_code == 200, response.text
    body = response.json()
    assert len(body["items"]) == 2
    siglas = {item["sigla_uf"] for item in body["items"]}
    assert siglas == {"SP", "RJ"}
    for item in body["items"]:
        assert item["cluster_id"] in (1, 2)
        assert item["ano_referencia"] == 2023
        assert item["centroid_pca_x"] is not None
        assert item["features_norm"] is not None


def test_clusters_filter_by_uf(_clusters_db_harness):
    from fastapi.testclient import TestClient

    h = _clusters_db_harness
    _seed_clusters(h)

    with TestClient(h["app"]) as local_client:
        response = local_client.get("/clusters", params={"uf": "sp"})

    assert response.status_code == 200, response.text
    body = response.json()
    assert len(body["items"]) == 1
    assert body["items"][0]["sigla_uf"] == "SP"


def test_clusters_no_data_returns_503(_clusters_db_harness):
    from fastapi.testclient import TestClient

    h = _clusters_db_harness
    # No rows seeded — ano_referencia auto-resolution should find nothing.

    with TestClient(h["app"]) as local_client:
        response = local_client.get("/clusters")

    assert response.status_code == 503


def test_clusters_uf_summary_sample_mode_503(client):
    response = client.get("/clusters/uf-summary")
    assert response.status_code == 503


def test_clusters_uf_summary_no_data_returns_503(_clusters_db_harness):
    from fastapi.testclient import TestClient

    h = _clusters_db_harness

    with TestClient(h["app"]) as local_client:
        response = local_client.get("/clusters/uf-summary")

    assert response.status_code == 503


def test_clusters_uf_summary_reads_uf_grain_table_not_municipio_average(
    _clusters_db_harness,
):
    """Regression: /clusters/uf-summary must serve rows straight from
    uf_cluster_assignments (a genuine UF-grain KMeans+PCA run), not aggregate
    municipio_cluster_assignments — averaging municipio-level PCA scores per
    UF collapsed pca_y toward zero for every UF (PCA scores are mean-centered
    at zero by construction), producing a flat-line scatter instead of a 2D
    one. Seeds contradicting values into MCA (a stale/irrelevant município
    row averaging to pca_y=0) to prove the endpoint ignores it entirely and
    serves UCA's real, non-zero pca_y instead.
    """
    from fastapi.testclient import TestClient

    h = _clusters_db_harness
    DimLocal = h["DimLocal"]
    MCA = h["MCA"]
    UCA = h["UCA"]
    insert = h["insert"]

    async def _seed():
        async with h["session_factory"]() as session:
            await session.execute(
                insert(DimLocal),
                [
                    {
                        "codigo_ibge_6": "355030",
                        "codigo_ibge_7": "3550308",
                        "nome_municipio": "Sao Paulo",
                        "nome_uf": "Sao Paulo",
                        "sigla_uf": "SP",
                        "codigo_uf": "35",
                        "regiao": "Sudeste",
                        "valid_from": datetime.date(2020, 1, 1),
                        "is_current": True,
                        "ativo": True,
                    }
                ],
            )
            await session.commit()
            local_id = (
                (await session.execute(DimLocal.__table__.select()))
                .mappings()
                .first()["id"]
            )

            # A município-grain row whose pca_y would average to 0 if this
            # endpoint (incorrectly) fell back to aggregating MCA.
            await session.execute(
                insert(MCA),
                [
                    {
                        "dim_local_id": local_id,
                        "cluster_id": 1,
                        "algoritmo": "KMeans",
                        "n_clusters": 3,
                        "ano_referencia": 2023,
                        "cluster_nome": "Perfil A",
                        "pca_x": 1.0,
                        "pca_y": 0.0,
                    },
                ],
            )
            # The real UF-grain run — distinct, non-zero pca_y.
            await session.execute(
                insert(UCA),
                [
                    {
                        "sigla_uf": "SP",
                        "cluster_id": 4,
                        "algoritmo": "KMeans",
                        "n_clusters": 5,
                        "ano_referencia": 2023,
                        "cluster_nome": "Perfil D",
                        "pca_x": 2.5,
                        "pca_y": -3.7,
                        "n_municipios": 645,
                    },
                    {
                        "sigla_uf": "RJ",
                        "cluster_id": 2,
                        "algoritmo": "KMeans",
                        "n_clusters": 5,
                        "ano_referencia": 2023,
                        "cluster_nome": "Perfil C",
                        "pca_x": -1.1,
                        "pca_y": 4.2,
                        "n_municipios": 92,
                    },
                ],
            )
            await session.commit()

    asyncio.run(_seed())

    with TestClient(h["app"]) as local_client:
        response = local_client.get("/clusters/uf-summary")

    assert response.status_code == 200, response.text
    body = response.json()
    by_uf = {row["sigla_uf"]: row for row in body}

    assert set(by_uf.keys()) == {"SP", "RJ"}

    sp = by_uf["SP"]
    assert sp["pca_x"] == pytest.approx(2.5)
    assert sp["pca_y"] == pytest.approx(-3.7)
    assert sp["cluster_id"] == 4
    assert sp["n_municipios"] == 645

    rj = by_uf["RJ"]
    assert rj["pca_y"] == pytest.approx(4.2)


def test_clusters_uf_summary_pca_y_has_real_variance_across_ufs(_clusters_db_harness):
    """Smoke check: with independent UF-grain rows, pca_y is not
    uniformly 0.000 across every UF — the symptom this whole fix addresses."""
    from fastapi.testclient import TestClient

    h = _clusters_db_harness
    UCA = h["UCA"]
    insert = h["insert"]

    ufs_pca_y = {"SP": -3.7, "RJ": 4.2, "MG": 0.9, "BA": -1.5}

    async def _seed():
        async with h["session_factory"]() as session:
            await session.execute(
                insert(UCA),
                [
                    {
                        "sigla_uf": uf,
                        "cluster_id": i % 5,
                        "algoritmo": "KMeans",
                        "n_clusters": 5,
                        "ano_referencia": 2023,
                        "cluster_nome": f"Perfil {i}",
                        "pca_x": float(i),
                        "pca_y": pca_y,
                        "n_municipios": 10 + i,
                    }
                    for i, (uf, pca_y) in enumerate(ufs_pca_y.items())
                ],
            )
            await session.commit()

    asyncio.run(_seed())

    with TestClient(h["app"]) as local_client:
        response = local_client.get("/clusters/uf-summary")

    assert response.status_code == 200, response.text
    body = response.json()
    pca_y_values = {row["pca_y"] for row in body}

    assert pca_y_values != {0.0}
    assert len(pca_y_values) > 1
