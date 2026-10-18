"""Tests for GET /risco-prospectivo: registration, input validation, and the
DB-backed behavioral coverage (peer distribution, sample-size and
404 branches, zero-rate exclusion) via an in-memory SQLite harness.
These tests run under the existing SAMPLE_MODE=true suite invocation with no
PostgreSQL.
"""

import asyncio
import datetime
import math

import numpy as np
import pytest


def test_risco_prospectivo_sample_mode_503(client):
    response = client.get(
        "/risco-prospectivo/", params={"municipio": "355030", "ano_referencia": 2021}
    )
    assert response.status_code == 503


def test_openapi_schema_risco_prospectivo(client):
    response = client.get("/openapi.json")
    assert response.status_code == 200
    paths = response.json()["paths"]
    # FastAPI registers prefix="/risco-prospectivo" + get("/") as "/risco-prospectivo/"
    # in the OpenAPI schema. Check for either form to be robust across FastAPI
    # trailing-slash handling.
    assert any(p.startswith("/risco-prospectivo") for p in paths)


@pytest.mark.parametrize("ano_referencia", [1800, 3000])
def test_risco_prospectivo_rejects_out_of_range_ano_referencia(client, ano_referencia):
    """V5 input-validation bound: ano_referencia is Query(..., ge=1990, le=2100)."""
    response = client.get(
        "/risco-prospectivo/",
        params={"municipio": "355030", "ano_referencia": ano_referencia},
    )
    assert response.status_code == 422


def test_risco_prospectivo_rejects_oversized_municipio(client):
    """V5 input-validation bound: municipio is Query(..., max_length=6)."""
    response = client.get(
        "/risco-prospectivo/", params={"municipio": "1234567", "ano_referencia": 2021}
    )
    assert response.status_code == 422


@pytest.mark.parametrize(
    "params",
    [
        {"municipio": "355030"},
        {"ano_referencia": 2021},
        {},
    ],
)
def test_risco_prospectivo_requires_both_params(client, params):
    response = client.get("/risco-prospectivo/", params=params)
    assert response.status_code == 422


@pytest.fixture
def _risco_prospectivo_db_harness(monkeypatch):
    """Isolated in-memory SQLite override for DB-backed risco_prospectivo coverage.

    Mirrors the harness in test_routers_clusters.py — router module import
    (not fresh `from app.config import ...`) to avoid the stale-singleton
    caveat documented in test_routers_indicadores.py.
    """
    from sqlalchemy import MetaData, insert
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
    from sqlalchemy.pool import StaticPool

    from app.main import app
    from app.models.dimensions import DimLocal
    from app.models.ml_results import MunicipioClusterAssignments as MCA
    from app.routers import risco_prospectivo as risco_prospectivo_module

    settings = risco_prospectivo_module.settings
    get_db = risco_prospectivo_module.get_db

    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    orm_metadata = MetaData()
    DimLocal.__table__.to_metadata(orm_metadata)
    MCA.__table__.to_metadata(orm_metadata)
    # mv_taxa_municipio_ano has NO ORM model — it's a raw Table() in
    # risco_prospectivo.py, not backed by Base (SQLite cannot create a
    # PostgreSQL materialized view). Table() is DB-agnostic DDL though —
    # "materialized view"-ness is a PostgreSQL runtime concept, not a schema-
    # shape concept — so reattaching the router's raw Table onto this
    # isolated MetaData via to_metadata() and running create_all produces a
    # same-shaped plain SQLite table. This is why the router declares the
    # view as a raw Table rather than a view-only construct.
    risco_prospectivo_module.mv_taxa_municipio_ano.to_metadata(orm_metadata)

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
        "mv": orm_metadata.tables["mv_taxa_municipio_ano"],
        "app": app,
        "get_db": get_db,
    }

    app.dependency_overrides.pop(get_db, None)
    asyncio.run(engine.dispose())


def _codigo(prefix: str, i: int | None = None) -> str:
    """Build a distinct 6-digit codigo_ibge_6. i=None -> target codigo for the prefix."""
    if i is None:
        return f"{prefix}00000"
    return f"{prefix}00{i + 1:03d}"


def _seed(h, *, peers, target_taxas, incluir_t3=True, codigo_prefix="1"):
    """Seed a target município plus N cluster peers, their MunicipioClusterAssignments
    rows (algoritmo=KMeans, n_clusters=6, ano_referencia=2021) and mv_taxa_municipio_ano
    rows (fonte=SIM) for T=2021 and — unless incluir_t3=False — T+3=2024.

    peers: list of dicts with keys `cluster_id`, `taxa_t` (float | None), `taxa_t3`
        (float | None). A None taxa means no mv row is inserted for that (codigo, ano).
    target_taxas: dict with keys `cluster_id`, `taxa_t`, `taxa_t3` (same None semantics).
    incluir_t3: if False, no mv rows are inserted for ano=2024 at all — simulates
        the "no real T+3 data" case.
    codigo_prefix: single-digit namespace so multiple _seed() calls against the same
        harness instance never collide on codigo_ibge_6.

    Returns the target's codigo_ibge_6.
    """
    DimLocal = h["DimLocal"]
    MCA = h["MCA"]
    mv = h["mv"]
    insert = h["insert"]

    target_codigo = _codigo(codigo_prefix)

    dim_local_rows = [
        {
            "codigo_ibge_6": target_codigo,
            "codigo_ibge_7": target_codigo + "0",
            "nome_municipio": "Target Municipio",
            "nome_uf": "Sao Paulo",
            "sigla_uf": "SP",
            "codigo_uf": "35",
            "regiao": "Sudeste",
            "valid_from": datetime.date(2020, 1, 1),
            "is_current": True,
            "ativo": True,
        }
    ]
    for i in range(len(peers)):
        codigo = _codigo(codigo_prefix, i)
        dim_local_rows.append(
            {
                "codigo_ibge_6": codigo,
                "codigo_ibge_7": codigo + "0",
                "nome_municipio": f"Peer Municipio {i}",
                "nome_uf": "Sao Paulo",
                "sigla_uf": "SP",
                "codigo_uf": "35",
                "regiao": "Sudeste",
                "valid_from": datetime.date(2020, 1, 1),
                "is_current": True,
                "ativo": True,
            }
        )

    cluster_rows = [{"codigo": target_codigo, "cluster_id": target_taxas["cluster_id"]}]
    for i, peer in enumerate(peers):
        cluster_rows.append(
            {"codigo": _codigo(codigo_prefix, i), "cluster_id": peer["cluster_id"]}
        )

    mv_rows = []
    if target_taxas.get("taxa_t") is not None:
        mv_rows.append((target_codigo, 2021, target_taxas["taxa_t"]))
    if incluir_t3 and target_taxas.get("taxa_t3") is not None:
        mv_rows.append((target_codigo, 2024, target_taxas["taxa_t3"]))
    for i, peer in enumerate(peers):
        codigo = _codigo(codigo_prefix, i)
        if peer.get("taxa_t") is not None:
            mv_rows.append((codigo, 2021, peer["taxa_t"]))
        if incluir_t3 and peer.get("taxa_t3") is not None:
            mv_rows.append((codigo, 2024, peer["taxa_t3"]))

    async def _seed_async():
        async with h["session_factory"]() as session:
            await session.execute(insert(DimLocal), dim_local_rows)
            await session.commit()
            result = await session.execute(DimLocal.__table__.select())
            id_by_codigo = {row.codigo_ibge_6: row.id for row in result.all()}

            await session.execute(
                insert(MCA),
                [
                    {
                        "dim_local_id": id_by_codigo[row["codigo"]],
                        "cluster_id": row["cluster_id"],
                        "algoritmo": "KMeans",
                        "n_clusters": 6,
                        "ano_referencia": 2021,
                    }
                    for row in cluster_rows
                ],
            )
            await session.commit()

            if mv_rows:
                await session.execute(
                    insert(mv),
                    [
                        {
                            "codigo_ibge_6": codigo,
                            "ano": ano,
                            "fonte": "SIM",
                            "taxa_por_100k": taxa,
                        }
                        for codigo, ano, taxa in mv_rows
                    ],
                )
                await session.commit()

    asyncio.run(_seed_async())
    return target_codigo


def test_risco_prospectivo_harness_smoke(_risco_prospectivo_db_harness):
    """Fixture-smoke test: harness creates all three tables and a seeded
    11-peer request returns 200. Deep assertions live in the tests below."""
    from fastapi.testclient import TestClient

    h = _risco_prospectivo_db_harness
    orm_metadata = h["mv"].metadata
    assert {
        "dim_local",
        "municipio_cluster_assignments",
        "mv_taxa_municipio_ano",
    } <= set(orm_metadata.tables)

    peers = [
        {"cluster_id": 1, "taxa_t": 100.0, "taxa_t3": 100.0 * (1 + delta)}
        for delta in [-0.5, -0.4, -0.3, -0.2, -0.1, 0.0, 0.1, 0.2, 0.3, 0.4, 0.5]
    ]
    target_codigo = _seed(
        h,
        peers=peers,
        target_taxas={"cluster_id": 1, "taxa_t": 100.0, "taxa_t3": 110.0},
    )

    with TestClient(h["app"]) as local_client:
        response = local_client.get(
            "/risco-prospectivo/",
            params={"municipio": target_codigo, "ano_referencia": 2021},
        )

    assert response.status_code == 200, response.text


def _get(h, target_codigo, ano_referencia=2021):
    from fastapi.testclient import TestClient

    with TestClient(h["app"]) as local_client:
        return local_client.get(
            "/risco-prospectivo/",
            params={"municipio": target_codigo, "ano_referencia": ano_referencia},
        )


def test_distribuicao_com_amostra_suficiente(_risco_prospectivo_db_harness):
    """Percentage-change formula, IQR + min/max, and n>=10 as a sufficient sample."""
    h = _risco_prospectivo_db_harness

    deltas = [-0.5, -0.4, -0.3, -0.2, -0.1, 0.0, 0.1, 0.2, 0.3, 0.4, 0.5]
    peers = [
        {"cluster_id": 1, "taxa_t": 100.0, "taxa_t3": 100.0 * (1 + d)} for d in deltas
    ]
    target_codigo = _seed(
        h,
        peers=peers,
        target_taxas={"cluster_id": 1, "taxa_t": 100.0, "taxa_t3": 110.0},
    )

    response = _get(h, target_codigo)

    assert response.status_code == 200, response.text
    body = response.json()
    dist = body["distribuicao_peers"]
    assert dist["n"] == 11
    assert dist["amostra_insuficiente"] is False
    for key in ("mediana", "p25", "p75", "minimo", "maximo"):
        assert dist[key] is not None
    assert (
        dist["minimo"]
        <= dist["p25"]
        <= dist["mediana"]
        <= dist["p75"]
        <= dist["maximo"]
    )
    expected_changes = np.array(deltas)
    assert dist["mediana"] == pytest.approx(float(np.median(expected_changes)))


def test_alvo_excluido_da_distribuicao(_risco_prospectivo_db_harness):
    """The target município's own rate change is excluded from the peer distribution."""
    h = _risco_prospectivo_db_harness

    deltas = [-0.2, -0.15, -0.1, -0.05, 0.0, 0.05, 0.1, 0.15, 0.2, 0.15, -0.15]
    peers = [
        {"cluster_id": 1, "taxa_t": 100.0, "taxa_t3": 100.0 * (1 + d)} for d in deltas
    ]
    # Deliberately extreme target change: +500%.
    target_codigo = _seed(
        h,
        peers=peers,
        target_taxas={"cluster_id": 1, "taxa_t": 100.0, "taxa_t3": 600.0},
    )

    response = _get(h, target_codigo)

    assert response.status_code == 200, response.text
    body = response.json()
    dist = body["distribuicao_peers"]
    assert dist["n"] == 11
    assert body["variacao_municipio"] == pytest.approx(5.0)
    assert dist["maximo"] < body["variacao_municipio"]


def test_amostra_insuficiente_retorna_200_com_flag(_risco_prospectivo_db_harness):
    """Below-threshold peer count returns 200 with amostra_insuficiente=true,
    the small distribution still populated (flagged, not suppressed)."""
    h = _risco_prospectivo_db_harness

    peers = [
        {"cluster_id": 1, "taxa_t": 100.0, "taxa_t3": 110.0},
        {"cluster_id": 1, "taxa_t": 100.0, "taxa_t3": 90.0},
        {"cluster_id": 1, "taxa_t": 100.0, "taxa_t3": 105.0},
        {"cluster_id": 1, "taxa_t": 100.0, "taxa_t3": 95.0},
    ]
    target_codigo = _seed(
        h,
        peers=peers,
        target_taxas={"cluster_id": 1, "taxa_t": 100.0, "taxa_t3": 100.0},
    )

    response = _get(h, target_codigo)

    assert response.status_code == 200
    assert response.status_code != 404
    assert response.status_code != 422
    body = response.json()
    dist = body["distribuicao_peers"]
    assert dist["n"] == 4
    assert dist["amostra_insuficiente"] is True
    assert dist["mediana"] is not None


def test_limite_exato_de_dez_peers(_risco_prospectivo_db_harness):
    """Boundary: n==10 is sufficient (amostra_insuficiente False); n==9 is not (True).
    Pins n < 10, not an off-by-one n <= 10."""
    h = _risco_prospectivo_db_harness

    def _make_peers(count, cluster_id):
        return [
            {"cluster_id": cluster_id, "taxa_t": 100.0, "taxa_t3": 100.0 + i}
            for i in range(count)
        ]

    # Distinct cluster_id per seed call — otherwise the second call's peers
    # would be visible to the first call's target (same cluster), and vice versa.
    target_codigo_10 = _seed(
        h,
        peers=_make_peers(10, cluster_id=1),
        target_taxas={"cluster_id": 1, "taxa_t": 100.0, "taxa_t3": 100.0},
        codigo_prefix="1",
    )
    response_10 = _get(h, target_codigo_10)
    assert response_10.status_code == 200, response_10.text
    dist_10 = response_10.json()["distribuicao_peers"]
    assert dist_10["n"] == 10
    assert dist_10["amostra_insuficiente"] is False

    target_codigo_9 = _seed(
        h,
        peers=_make_peers(9, cluster_id=2),
        target_taxas={"cluster_id": 2, "taxa_t": 100.0, "taxa_t3": 100.0},
        codigo_prefix="2",
    )
    response_9 = _get(h, target_codigo_9)
    assert response_9.status_code == 200, response_9.text
    dist_9 = response_9.json()["distribuicao_peers"]
    assert dist_9["n"] == 9
    assert dist_9["amostra_insuficiente"] is True


def test_peer_com_taxa_zero_em_t_e_excluido(_risco_prospectivo_db_harness):
    """A peer with taxa_T == 0 is excluded from the
    distribution and from n before it is computed — no 500, no inf/NaN."""
    h = _risco_prospectivo_db_harness

    deltas = [-0.4, -0.3, -0.2, -0.1, 0.0, 0.1, 0.2, 0.3, 0.4, 0.5]
    peers = [
        {"cluster_id": 1, "taxa_t": 100.0, "taxa_t3": 100.0 * (1 + d)} for d in deltas
    ]
    # 11th peer: taxa_T == 0 with a non-zero taxa_T3 — must be excluded, not divide-by-zero.
    peers.append({"cluster_id": 1, "taxa_t": 0.0, "taxa_t3": 50.0})
    target_codigo = _seed(
        h,
        peers=peers,
        target_taxas={"cluster_id": 1, "taxa_t": 100.0, "taxa_t3": 110.0},
    )

    response = _get(h, target_codigo)

    assert response.status_code == 200, response.text
    body = response.json()
    dist = body["distribuicao_peers"]
    assert dist["n"] == 10
    for key in ("mediana", "p25", "p75", "minimo", "maximo"):
        assert math.isfinite(dist[key])


def test_sem_dados_em_t_mais_3_retorna_404(_risco_prospectivo_db_harness):
    """No real T+3 (2024) mv_taxa_municipio_ano rows exist -> 404, mentioning 2024."""
    h = _risco_prospectivo_db_harness

    peers = [{"cluster_id": 1, "taxa_t": 100.0, "taxa_t3": 110.0} for _ in range(11)]
    target_codigo = _seed(
        h,
        peers=peers,
        target_taxas={"cluster_id": 1, "taxa_t": 100.0, "taxa_t3": 110.0},
        incluir_t3=False,
    )

    response = _get(h, target_codigo)

    assert response.status_code == 404
    assert "2024" in response.json()["detail"]


def test_municipio_sem_cluster_no_ano_retorna_404(_risco_prospectivo_db_harness):
    """Cluster rows exist only for ano_referencia=2021 (seed default); requesting
    a different reference year with no cluster assignment -> 404."""
    h = _risco_prospectivo_db_harness

    peers = [{"cluster_id": 1, "taxa_t": 100.0, "taxa_t3": 110.0} for _ in range(11)]
    target_codigo = _seed(
        h,
        peers=peers,
        target_taxas={"cluster_id": 1, "taxa_t": 100.0, "taxa_t3": 110.0},
    )

    response = _get(h, target_codigo, ano_referencia=2015)

    assert response.status_code == 404


def test_municipio_inexistente_retorna_404(_risco_prospectivo_db_harness):
    h = _risco_prospectivo_db_harness

    peers = [{"cluster_id": 1, "taxa_t": 100.0, "taxa_t3": 110.0} for _ in range(11)]
    _seed(
        h,
        peers=peers,
        target_taxas={"cluster_id": 1, "taxa_t": 100.0, "taxa_t3": 110.0},
    )

    response = _get(h, "999999")

    assert response.status_code == 404


def test_peers_de_outro_cluster_sao_ignorados(_risco_prospectivo_db_harness):
    """Peers in a different cluster than the target's are excluded from n."""
    h = _risco_prospectivo_db_harness

    peers_cluster_1 = [
        {"cluster_id": 1, "taxa_t": 100.0, "taxa_t3": 110.0} for _ in range(11)
    ]
    peers_cluster_2 = [
        {"cluster_id": 2, "taxa_t": 100.0, "taxa_t3": 90.0} for _ in range(5)
    ]
    target_codigo = _seed(
        h,
        peers=peers_cluster_1 + peers_cluster_2,
        target_taxas={"cluster_id": 1, "taxa_t": 100.0, "taxa_t3": 110.0},
    )

    response = _get(h, target_codigo)

    assert response.status_code == 200, response.text
    assert response.json()["distribuicao_peers"]["n"] == 11


def test_resposta_carrega_tipo_analise(_risco_prospectivo_db_harness):
    """Every 200 response carries tipo_analise = comparacao_prospectiva, and the
    serialized body contains no case-insensitive occurrence of 'previsao'."""
    h = _risco_prospectivo_db_harness

    peers = [{"cluster_id": 1, "taxa_t": 100.0, "taxa_t3": 110.0} for _ in range(11)]
    target_codigo = _seed(
        h,
        peers=peers,
        target_taxas={"cluster_id": 1, "taxa_t": 100.0, "taxa_t3": 110.0},
    )

    response = _get(h, target_codigo)

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["tipo_analise"] == "comparacao_prospectiva"
    assert "previsao" not in response.text.lower()
