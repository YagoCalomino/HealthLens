"""Tests for GET /notificacoes/, /notificacoes/uf-summary and
/notificacoes/municipio-summary.

Mirrors the in-memory SQLite harness pattern established by
test_routers_risco_prospectivo.py (`_risco_prospectivo_db_harness`): router
module attributes (not fresh `from app.config import ...` statements) are
patched, since test_health.py's CORS-wildcard test purges and re-imports
app.main/app.config, which would otherwise leave a freshly-imported
`settings` singleton unpatched.
"""

import asyncio
import datetime

import pytest

# These endpoints read PostgreSQL materialized views (mv_uf_summary_anual,
# mv_curva_epidemica_semana, mv_breakdown_anual, ...) created by Alembic
# migrations; the in-memory SQLite harness below has no equivalent.
requires_postgres_mvs = pytest.mark.skip(
    reason="requires PostgreSQL materialized views (mv_*), absent from the SQLite harness"
)


def test_notificacoes_root_sample_mode_503(client):
    response = client.get("/notificacoes/")
    assert response.status_code == 503


def test_openapi_schema_notificacoes(client):
    response = client.get("/openapi.json")
    assert response.status_code == 200
    paths = response.json()["paths"]
    assert any(p.startswith("/notificacoes") for p in paths)


@pytest.mark.parametrize("agravo", ["XXXX", "deng", "sinan"])
def test_notificacoes_rejects_invalid_agravo(client, agravo):
    """agravo is Literal["DENG","CHIK","ANIM"] — anything else, including a
    lowercase valid code, is rejected with 422."""
    response = client.get("/notificacoes/", params={"agravo": agravo})
    assert response.status_code == 422


@pytest.mark.parametrize("ano_inicio", [1800, 3000])
def test_notificacoes_rejects_out_of_range_ano_inicio(client, ano_inicio):
    """V5 input-validation bound: ano_inicio is Query(default=None, ge=1990, le=2100)."""
    response = client.get("/notificacoes/", params={"ano_inicio": ano_inicio})
    assert response.status_code == 422


def test_notificacoes_rejects_oversized_municipio(client):
    """V5 input-validation bound: municipio is Query(default=None, max_length=6)."""
    response = client.get("/notificacoes/", params={"municipio": "1234567"})
    assert response.status_code == 422


@pytest.fixture
def _notificacoes_db_harness(monkeypatch):
    """Isolated in-memory SQLite override for DB-backed /notificacoes coverage.

    Creates dim_tempo, dim_local, dim_agravo, dim_faixa_etaria and
    fato_notificacoes from the real ORM metadata, overrides the
    router module's DB dependency, and yields helpers for seeding + querying.
    """
    from sqlalchemy import MetaData, insert
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
    from sqlalchemy.pool import StaticPool

    from app.main import app
    from app.models.dimensions import DimAgravo, DimFaixaEtaria, DimLocal, DimTempo
    from app.models.facts import FatoNotificacoes
    from app.routers import notificacoes as notificacoes_module

    settings = notificacoes_module.settings
    get_db = notificacoes_module.get_db

    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    orm_metadata = MetaData()
    DimTempo.__table__.to_metadata(orm_metadata)
    DimLocal.__table__.to_metadata(orm_metadata)
    DimAgravo.__table__.to_metadata(orm_metadata)
    DimFaixaEtaria.__table__.to_metadata(orm_metadata)
    FatoNotificacoes.__table__.to_metadata(orm_metadata)

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
        "DimTempo": orm_metadata.tables["dim_tempo"],
        "DimLocal": orm_metadata.tables["dim_local"],
        "DimAgravo": orm_metadata.tables["dim_agravo"],
        "DimFaixaEtaria": orm_metadata.tables["dim_faixa_etaria"],
        "FatoNotificacoes": orm_metadata.tables["fato_notificacoes"],
        "app": app,
        "get_db": get_db,
    }

    app.dependency_overrides.pop(get_db, None)
    asyncio.run(engine.dispose())


_MUNICIPIOS = [
    {
        "codigo_ibge_6": "355030",
        "codigo_ibge_7": "3550308",
        "nome_municipio": "Sao Paulo",
        "nome_uf": "Sao Paulo",
        "sigla_uf": "SP",
        "codigo_uf": "35",
        "regiao": "Sudeste",
    },
    {
        "codigo_ibge_6": "355100",
        "codigo_ibge_7": "3551009",
        "nome_municipio": "Santo Andre",
        "nome_uf": "Sao Paulo",
        "sigla_uf": "SP",
        "codigo_uf": "35",
        "regiao": "Sudeste",
    },
    {
        "codigo_ibge_6": "330455",
        "codigo_ibge_7": "3304557",
        "nome_municipio": "Rio de Janeiro",
        "nome_uf": "Rio de Janeiro",
        "sigla_uf": "RJ",
        "codigo_uf": "33",
        "regiao": "Sudeste",
    },
]

_AGRAVOS = ["DENG", "CHIK", "ANIM"]
_ANOS = [2023, 2024]
_FAIXAS = [
    {
        "codigo": "20-29",
        "descricao": "20 a 29 anos",
        "idade_min": 20,
        "idade_max": 29,
        "ordem": 5,
    },
    {
        "codigo": "30-39",
        "descricao": "30 a 39 anos",
        "idade_min": 30,
        "idade_max": 39,
        "ordem": 6,
    },
]

# Number of seeded fato_notificacoes rows — comfortably above the default
# CursorParams page size (50), so a full cursor walk crosses at least one
# page boundary.
_N_ROWS = 63


def _seed_notificacoes(h):
    """Seed dimensions + >= 60 fato_notificacoes rows, deterministic and
    reproducible. Returns a dict describing every inserted fact row (as
    plain python values) plus dimension lookup metadata, so tests can
    independently compute oracle aggregates instead of re-deriving them
    from the API response under test.
    """
    DimTempo = h["DimTempo"]
    DimLocal = h["DimLocal"]
    DimAgravo = h["DimAgravo"]
    DimFaixaEtaria = h["DimFaixaEtaria"]
    FatoNotificacoes = h["FatoNotificacoes"]
    insert = h["insert"]

    dim_tempo_rows = [
        {"ano": ano, "mes": None, "trimestre": None, "semestre": None} for ano in _ANOS
    ]
    dim_local_rows = [
        {
            **m,
            "valid_from": datetime.date(2020, 1, 1),
            "is_current": True,
            "ativo": True,
            "codigo_sucessor": None,
        }
        for m in _MUNICIPIOS
    ]
    dim_agravo_rows = [{"codigo": a, "descricao": a} for a in _AGRAVOS]
    dim_faixa_rows = list(_FAIXAS)

    facts: list[dict] = []
    for i in range(_N_ROWS):
        agravo = _AGRAVOS[i % 3]
        municipio = _MUNICIPIOS[i % 3]
        ano = _ANOS[i % 2]
        faixa = _FAIXAS[i % 2]

        classi_fin = None
        tra_classi = None
        tp_acidente = None
        if agravo == "DENG":
            classi_fin = 10 if i % 4 != 1 else 5
        elif agravo == "CHIK":
            classi_fin = 13
        else:  # ANIM never has classi_fin — no source column at all
            tra_classi = 1 + (i % 3)
            tp_acidente = 1 + (i % 6)

        taxa = None if i % 11 == 0 else round(1.0 + (i % 20) * 0.5, 4)

        facts.append(
            {
                "agravo": agravo,
                "codigo_ibge_6": municipio["codigo_ibge_6"],
                "sigla_uf": municipio["sigla_uf"],
                "ano": ano,
                "faixa_codigo": faixa["codigo"],
                "numero_notificacao": f"NOT{i:05d}",
                "notificacoes": 1,
                "taxa_por_100k": taxa,
                "sexo": "M" if i % 2 == 0 else "F",
                "idade_anos": 20 + (i % 40),
                "classi_fin": classi_fin,
                "gravidade_grave": (i % 7 == 0),
                "tra_classi": tra_classi,
                "tp_acidente": tp_acidente,
                "dt_notific": datetime.date(ano, ((i % 12) + 1), 10),
            }
        )

    # Force the plan's explicit required rows deterministically at fixed indices.
    facts[0].update(agravo="DENG", classi_fin=10)
    facts[1].update(agravo="DENG", classi_fin=5)
    facts[2].update(
        agravo="ANIM", classi_fin=None, tra_classi=1, tp_acidente=3, dt_notific=None
    )
    facts[3]["taxa_por_100k"] = None

    async def _seed_async():
        async with h["session_factory"]() as session:
            await session.execute(insert(DimTempo), dim_tempo_rows)
            await session.execute(insert(DimLocal), dim_local_rows)
            await session.execute(insert(DimAgravo), dim_agravo_rows)
            await session.execute(insert(DimFaixaEtaria), dim_faixa_rows)
            await session.commit()

            tempo_rows = (await session.execute(DimTempo.select())).mappings().all()
            tempo_id_by_ano = {r["ano"]: r["id"] for r in tempo_rows}

            local_rows = (await session.execute(DimLocal.select())).mappings().all()
            local_id_by_codigo = {r["codigo_ibge_6"]: r["id"] for r in local_rows}

            agravo_rows = (await session.execute(DimAgravo.select())).mappings().all()
            agravo_id_by_codigo = {r["codigo"]: r["id"] for r in agravo_rows}

            faixa_rows = (
                (await session.execute(DimFaixaEtaria.select())).mappings().all()
            )
            faixa_id_by_codigo = {r["codigo"]: r["id"] for r in faixa_rows}

            insert_rows = [
                {
                    # Explicit id: SQLite's BIGINT-typed primary key does not
                    # reliably alias to the rowid autoincrement column the
                    # way a plain INTEGER PRIMARY KEY does, so autoincrement
                    # cannot be relied on here — assign ids deterministically
                    # instead (tests rely on strictly-increasing, gap-free ids).
                    "id": i + 1,
                    "dim_tempo_id": tempo_id_by_ano[f["ano"]],
                    "dim_local_id": local_id_by_codigo[f["codigo_ibge_6"]],
                    "dim_agravo_id": agravo_id_by_codigo[f["agravo"]],
                    "dim_faixa_etaria_id": faixa_id_by_codigo[f["faixa_codigo"]],
                    "tipo_agravo": f["agravo"],
                    "numero_notificacao": f["numero_notificacao"],
                    "notificacoes": f["notificacoes"],
                    "taxa_por_100k": f["taxa_por_100k"],
                    "sexo": f["sexo"],
                    "idade_anos": f["idade_anos"],
                    "classi_fin": f["classi_fin"],
                    "gravidade_grave": f["gravidade_grave"],
                    "tra_classi": f["tra_classi"],
                    "tp_acidente": f["tp_acidente"],
                    "dt_notific": f["dt_notific"],
                }
                for i, f in enumerate(facts)
            ]
            await session.execute(insert(FatoNotificacoes), insert_rows)
            await session.commit()

    asyncio.run(_seed_async())
    # ids are sequential (1..N) on a freshly created in-memory SQLite table.
    ids = list(range(1, _N_ROWS + 1))
    for fact, row_id in zip(facts, ids):
        fact["id"] = row_id
    return facts


def _client(h):
    from fastapi.testclient import TestClient

    return TestClient(h["app"])


def test_notificacoes_filter_by_agravo(_notificacoes_db_harness):
    h = _notificacoes_db_harness
    _seed_notificacoes(h)

    with _client(h) as c:
        response = c.get("/notificacoes/", params={"agravo": "DENG"})

    assert response.status_code == 200, response.text
    items = response.json()["items"]
    assert len(items) > 0
    assert all(item["agravo"] == "DENG" for item in items)


def test_notificacoes_filter_by_uf(_notificacoes_db_harness):
    h = _notificacoes_db_harness
    facts = _seed_notificacoes(h)
    expected_ids = {f["id"] for f in facts if f["sigla_uf"] == "SP"}

    collected_ids: set[int] = set()
    cursor = None
    with _client(h) as c:
        while True:
            params = {"uf": "SP", "size": 100}
            if cursor:
                params["cursor"] = cursor
            response = c.get("/notificacoes/", params=params)
            assert response.status_code == 200, response.text
            body = response.json()
            for item in body["items"]:
                collected_ids.add(item["id"])
                assert item["sigla_uf"] == "SP"
            cursor = body.get("next_page")
            if not cursor:
                break

    assert collected_ids == expected_ids


def test_notificacoes_filter_by_municipio(_notificacoes_db_harness):
    h = _notificacoes_db_harness
    facts = _seed_notificacoes(h)
    expected_ids = {f["id"] for f in facts if f["codigo_ibge_6"] == "355030"}

    with _client(h) as c:
        response = c.get("/notificacoes/", params={"municipio": "355030", "size": 100})

    assert response.status_code == 200, response.text
    items = response.json()["items"]
    assert {item["id"] for item in items} == expected_ids
    assert all(item["codigo_ibge"] == "3550308" for item in items)


def test_notificacoes_ano_inicio_excludes_earlier_years(_notificacoes_db_harness):
    h = _notificacoes_db_harness
    _seed_notificacoes(h)

    with _client(h) as c:
        response = c.get("/notificacoes/", params={"ano_inicio": 2024, "size": 100})

    assert response.status_code == 200, response.text
    items = response.json()["items"]
    assert len(items) > 0
    assert all(item["ano"] == 2024 for item in items)


def test_notificacoes_ano_fim_excludes_later_years(_notificacoes_db_harness):
    h = _notificacoes_db_harness
    _seed_notificacoes(h)

    with _client(h) as c:
        response = c.get("/notificacoes/", params={"ano_fim": 2023, "size": 100})

    assert response.status_code == 200, response.text
    items = response.json()["items"]
    assert len(items) > 0
    assert all(item["ano"] == 2023 for item in items)


def test_notificacoes_filter_by_classi_fin(_notificacoes_db_harness):
    h = _notificacoes_db_harness
    facts = _seed_notificacoes(h)
    expected_ids = {f["id"] for f in facts if f["classi_fin"] == 10}

    with _client(h) as c:
        response = c.get("/notificacoes/", params={"classi_fin": 10, "size": 100})

    assert response.status_code == 200, response.text
    items = response.json()["items"]
    assert {item["id"] for item in items} == expected_ids
    assert all(item["classi_fin"] == 10 for item in items)


def test_notificacoes_cursor_walk_no_dup_or_skip_and_strictly_increasing(
    _notificacoes_db_harness,
):
    h = _notificacoes_db_harness
    facts = _seed_notificacoes(h)
    expected_ids = [f["id"] for f in facts]

    collected: list[int] = []
    cursor = None
    pages_walked = 0
    max_pages = 20  # 63 rows / default size 50 => 2 pages expected; generous ceiling.
    with _client(h) as c:
        while True:
            params = {}
            if cursor:
                params["cursor"] = cursor
            response = c.get("/notificacoes/", params=params)
            assert response.status_code == 200, response.text
            body = response.json()
            for item in body["items"]:
                collected.append(item["id"])
            pages_walked += 1
            assert pages_walked <= max_pages, "pagination did not terminate"
            cursor = body.get("next_page")
            if not cursor:
                break

    assert pages_walked >= 2, "seeded row count did not actually cross a page boundary"
    assert sorted(collected) == sorted(expected_ids)
    assert len(collected) == len(set(collected)), "cursor walk produced duplicate ids"
    assert collected == sorted(collected), (
        "ids are not strictly increasing across the cursor walk"
    )


@requires_postgres_mvs
def test_notificacoes_uf_summary_shape_and_totals(_notificacoes_db_harness):
    h = _notificacoes_db_harness
    facts = _seed_notificacoes(h)
    deng_facts = [f for f in facts if f["agravo"] == "DENG"]

    expected_counts: dict[tuple[str, int], int] = {}
    for f in deng_facts:
        key = (f["sigla_uf"], f["ano"])
        expected_counts[key] = expected_counts.get(key, 0) + 1

    with _client(h) as c:
        response = c.get("/notificacoes/uf-summary", params={"agravo": "DENG"})

    assert response.status_code == 200, response.text
    body = response.json()
    assert "casos" not in "".join(body[0].keys()) if body else True
    seen_keys = set()
    for row in body:
        key = (row["sigla_uf"], row["ano"])
        assert key not in seen_keys, "duplicate (sigla_uf, ano) row in uf-summary"
        seen_keys.add(key)
        assert row["total_notificacoes"] == expected_counts[key]
        assert row["taxa_por_100k"] is None or row["taxa_por_100k"] >= 0
        assert "total_notificacoes" in row
    assert seen_keys == set(expected_counts.keys())


@requires_postgres_mvs
def test_notificacoes_uf_summary_taxa_not_sum_of_municipio_rates(
    _notificacoes_db_harness,
):
    """Regression: a UF's taxa_por_100k must be
    total_notificacoes * 100000 / total_populacao_dos_municipios, never the
    sum of each município's already-divided per-notification rate. Two SP
    municípios with very different populations (10k vs 10M) each get one
    ANIM notification in 2023 — summing their individual rates (10 + 0.01)
    would grossly overstate the UF rate; the correct combined rate is close
    to the low end, dominated by the large município's population.
    """
    h = _notificacoes_db_harness
    DimTempo = h["DimTempo"]
    DimLocal = h["DimLocal"]
    DimAgravo = h["DimAgravo"]
    DimFaixaEtaria = h["DimFaixaEtaria"]
    FatoNotificacoes = h["FatoNotificacoes"]
    insert = h["insert"]

    small_pop = 10_000
    large_pop = 10_000_000
    small_taxa = round(1.0 / small_pop * 100_000, 4)  # 1.0
    large_taxa = round(1.0 / large_pop * 100_000, 4)  # 0.01
    expected_uf_taxa = 2 * 100_000.0 / (small_pop + large_pop)  # ~0.02

    async def _seed():
        async with h["session_factory"]() as session:
            await session.execute(
                insert(DimTempo),
                [{"ano": 2023, "mes": None, "trimestre": None, "semestre": None}],
            )
            await session.execute(
                insert(DimLocal),
                [
                    {
                        "codigo_ibge_6": "355900",
                        "codigo_ibge_7": "3559009",
                        "nome_municipio": "Small Town",
                        "nome_uf": "Sao Paulo",
                        "sigla_uf": "SP",
                        "codigo_uf": "35",
                        "regiao": "Sudeste",
                        "valid_from": datetime.date(2020, 1, 1),
                        "is_current": True,
                        "ativo": True,
                        "codigo_sucessor": None,
                    },
                    {
                        "codigo_ibge_6": "355901",
                        "codigo_ibge_7": "3559017",
                        "nome_municipio": "Big City",
                        "nome_uf": "Sao Paulo",
                        "sigla_uf": "SP",
                        "codigo_uf": "35",
                        "regiao": "Sudeste",
                        "valid_from": datetime.date(2020, 1, 1),
                        "is_current": True,
                        "ativo": True,
                        "codigo_sucessor": None,
                    },
                ],
            )
            await session.execute(
                insert(DimAgravo), [{"codigo": "ANIM", "descricao": "ANIM"}]
            )
            await session.execute(
                insert(DimFaixaEtaria),
                [
                    {
                        "codigo": "20-29",
                        "descricao": "20 a 29 anos",
                        "idade_min": 20,
                        "idade_max": 29,
                        "ordem": 5,
                    }
                ],
            )
            await session.commit()

            tempo_id = (
                (await session.execute(DimTempo.select())).mappings().first()["id"]
            )
            agravo_id = (
                (await session.execute(DimAgravo.select())).mappings().first()["id"]
            )
            faixa_id = (
                (await session.execute(DimFaixaEtaria.select()))
                .mappings()
                .first()["id"]
            )
            locals_ = {
                r["codigo_ibge_6"]: r["id"]
                for r in (await session.execute(DimLocal.select())).mappings().all()
            }

            await session.execute(
                insert(FatoNotificacoes),
                [
                    {
                        "id": 1,
                        "dim_tempo_id": tempo_id,
                        "dim_local_id": locals_["355900"],
                        "dim_agravo_id": agravo_id,
                        "dim_faixa_etaria_id": faixa_id,
                        "tipo_agravo": "ANIM",
                        "numero_notificacao": "NOT00001",
                        "notificacoes": 1,
                        "taxa_por_100k": small_taxa,
                        "sexo": "M",
                        "idade_anos": 25,
                        "classi_fin": None,
                        "gravidade_grave": None,
                        "tra_classi": 1,
                        "tp_acidente": 1,
                        "dt_notific": datetime.date(2023, 6, 1),
                    },
                    {
                        "id": 2,
                        "dim_tempo_id": tempo_id,
                        "dim_local_id": locals_["355901"],
                        "dim_agravo_id": agravo_id,
                        "dim_faixa_etaria_id": faixa_id,
                        "tipo_agravo": "ANIM",
                        "numero_notificacao": "NOT00002",
                        "notificacoes": 1,
                        "taxa_por_100k": large_taxa,
                        "sexo": "F",
                        "idade_anos": 30,
                        "classi_fin": None,
                        "gravidade_grave": None,
                        "tra_classi": 1,
                        "tp_acidente": 1,
                        "dt_notific": datetime.date(2023, 6, 1),
                    },
                ],
            )
            await session.commit()

    asyncio.run(_seed())

    with _client(h) as c:
        response = c.get("/notificacoes/uf-summary", params={"agravo": "ANIM"})

    assert response.status_code == 200, response.text
    body = response.json()
    assert len(body) == 1
    row = body[0]
    assert row["sigla_uf"] == "SP"
    assert row["total_notificacoes"] == 2

    naive_sum = (
        small_taxa + large_taxa
    )  # what the old (buggy) SUM(taxa_por_100k) produced
    assert row["taxa_por_100k"] == pytest.approx(expected_uf_taxa, abs=1e-4)
    assert row["taxa_por_100k"] < naive_sum / 10, (
        "uf-summary taxa_por_100k looks like a sum of per-município rates, not "
        "total_notificacoes / total_populacao"
    )


@requires_postgres_mvs
def test_notificacoes_municipio_summary_uses_seven_digit_codigo(
    _notificacoes_db_harness,
):
    h = _notificacoes_db_harness
    _seed_notificacoes(h)

    # Aggregate grain is (codigo_ibge, agravo, ano) — filter to a single
    # agravo, as the uf-summary test also does, so (codigo_ibge, ano) is
    # unique within the response and the aggregate shape can be asserted cleanly.
    with _client(h) as c:
        response = c.get(
            "/notificacoes/municipio-summary", params={"uf": "SP", "agravo": "DENG"}
        )

    assert response.status_code == 200, response.text
    body = response.json()
    assert len(body) > 0
    seen_keys = set()
    for row in body:
        assert row["sigla_uf"] == "SP"
        assert row["codigo_ibge"] is not None
        assert len(row["codigo_ibge"]) == 7
        key = (row["codigo_ibge"], row["ano"])
        assert key not in seen_keys, (
            "duplicate (codigo_ibge, ano) row in municipio-summary"
        )
        seen_keys.add(key)
        assert "total_notificacoes" in row


@requires_postgres_mvs
def test_notificacoes_summary_endpoints_never_expose_casos_field(
    _notificacoes_db_harness,
):
    h = _notificacoes_db_harness
    _seed_notificacoes(h)

    with _client(h) as c:
        uf_resp = c.get("/notificacoes/uf-summary")
        mun_resp = c.get("/notificacoes/municipio-summary")

    assert uf_resp.status_code == 200, uf_resp.text
    assert mun_resp.status_code == 200, mun_resp.text
    for body in (uf_resp.json(), mun_resp.json()):
        assert len(body) > 0
        for row in body:
            assert "casos" not in row
            assert "total_notificacoes" in row


# ---------------------------------------------------------------------------
# GET /notificacoes/curva-epidemica
# ---------------------------------------------------------------------------


def _seed_curva_epidemica_rows(h):
    """Seed rows with controlled dt_notific values for the epi-week boundary
    assertions: two rows landing in (2023, 1),
    one in (2023, 2), one cross-year row landing in (2020, 53), and one
    NULL-dt_notific row that must be excluded from every bucket.
    """
    DimTempo = h["DimTempo"]
    DimLocal = h["DimLocal"]
    DimAgravo = h["DimAgravo"]
    DimFaixaEtaria = h["DimFaixaEtaria"]
    FatoNotificacoes = h["FatoNotificacoes"]
    insert = h["insert"]

    dim_tempo_rows = [
        {"ano": ano, "mes": None, "trimestre": None, "semestre": None}
        for ano in (2020, 2021, 2023)
    ]
    dim_local_rows = [
        {
            **_MUNICIPIOS[0],
            "valid_from": datetime.date(2020, 1, 1),
            "is_current": True,
            "ativo": True,
            "codigo_sucessor": None,
        }
    ]
    dim_agravo_rows = [{"codigo": "DENG", "descricao": "DENG"}]
    dim_faixa_rows = [_FAIXAS[0]]

    # (dt_notific, dim_tempo ano the row belongs to)
    rows_spec = [
        (datetime.date(2023, 1, 1), 2023),
        (datetime.date(2023, 1, 7), 2023),
        (datetime.date(2023, 1, 8), 2023),
        (datetime.date(2021, 1, 1), 2021),
        (None, 2023),
    ]

    async def _seed_async():
        async with h["session_factory"]() as session:
            await session.execute(insert(DimTempo), dim_tempo_rows)
            await session.execute(insert(DimLocal), dim_local_rows)
            await session.execute(insert(DimAgravo), dim_agravo_rows)
            await session.execute(insert(DimFaixaEtaria), dim_faixa_rows)
            await session.commit()

            tempo_rows = (await session.execute(DimTempo.select())).mappings().all()
            tempo_id_by_ano = {r["ano"]: r["id"] for r in tempo_rows}
            local_rows = (await session.execute(DimLocal.select())).mappings().all()
            local_id = local_rows[0]["id"]
            agravo_rows = (await session.execute(DimAgravo.select())).mappings().all()
            agravo_id = agravo_rows[0]["id"]
            faixa_rows = (
                (await session.execute(DimFaixaEtaria.select())).mappings().all()
            )
            faixa_id = faixa_rows[0]["id"]

            insert_rows = [
                {
                    "id": i + 1,
                    "dim_tempo_id": tempo_id_by_ano[ano],
                    "dim_local_id": local_id,
                    "dim_agravo_id": agravo_id,
                    "dim_faixa_etaria_id": faixa_id,
                    "tipo_agravo": "DENG",
                    "numero_notificacao": f"CURVA{i:03d}",
                    "notificacoes": 1,
                    "taxa_por_100k": 1.0,
                    "sexo": "M",
                    "idade_anos": 30,
                    "classi_fin": 10,
                    "gravidade_grave": False,
                    "tra_classi": None,
                    "tp_acidente": None,
                    "dt_notific": dt,
                }
                for i, (dt, ano) in enumerate(rows_spec)
            ]
            await session.execute(insert(FatoNotificacoes), insert_rows)
            await session.commit()

    asyncio.run(_seed_async())


def test_curva_epidemica_sample_mode_503(client):
    response = client.get("/notificacoes/curva-epidemica")
    assert response.status_code == 503


@requires_postgres_mvs
def test_curva_epidemica_epi_week_boundaries(_notificacoes_db_harness):
    h = _notificacoes_db_harness
    _seed_curva_epidemica_rows(h)

    with _client(h) as c:
        response = c.get(
            "/notificacoes/curva-epidemica",
            params={"agravo": "DENG", "ano_inicio": 2023, "ano_fim": 2023},
        )

    assert response.status_code == 200, response.text
    body = response.json()
    by_week = {
        (row["ano_epidemiologico"], row["semana_epidemiologica"]): row for row in body
    }

    assert by_week[(2023, 1)]["total_notificacoes"] == 2
    assert by_week[(2023, 2)]["total_notificacoes"] == 1

    keys = [(row["ano_epidemiologico"], row["semana_epidemiologica"]) for row in body]
    assert keys == sorted(keys)
    for row in body:
        assert 1 <= row["semana_epidemiologica"] <= 53


@requires_postgres_mvs
def test_curva_epidemica_cross_year_boundary_se53(_notificacoes_db_harness):
    h = _notificacoes_db_harness
    _seed_curva_epidemica_rows(h)

    with _client(h) as c:
        response = c.get(
            "/notificacoes/curva-epidemica",
            params={"agravo": "DENG", "ano_inicio": 2021, "ano_fim": 2021},
        )

    assert response.status_code == 200, response.text
    body = response.json()
    by_week = {
        (row["ano_epidemiologico"], row["semana_epidemiologica"]): row for row in body
    }
    assert (2020, 53) in by_week
    assert by_week[(2020, 53)]["total_notificacoes"] == 1


@requires_postgres_mvs
def test_curva_epidemica_zero_fills_gaps_in_range(_notificacoes_db_harness):
    h = _notificacoes_db_harness
    _seed_curva_epidemica_rows(h)

    with _client(h) as c:
        response = c.get(
            "/notificacoes/curva-epidemica",
            params={"agravo": "DENG", "ano_inicio": 2023, "ano_fim": 2023},
        )

    assert response.status_code == 200, response.text
    body = response.json()
    zero_weeks = [row for row in body if row["total_notificacoes"] == 0]
    assert len(zero_weeks) > 0


@requires_postgres_mvs
def test_curva_epidemica_excludes_null_dt_notific(_notificacoes_db_harness):
    h = _notificacoes_db_harness
    _seed_curva_epidemica_rows(h)

    with _client(h) as c:
        response = c.get(
            "/notificacoes/curva-epidemica",
            params={"agravo": "DENG", "ano_inicio": 2023, "ano_fim": 2023},
        )

    assert response.status_code == 200, response.text
    body = response.json()
    # 3 rows actually dated within 2023 (Jan 1, Jan 7, Jan 8); the NULL
    # dt_notific row must never be silently bucketed into week 1.
    assert sum(row["total_notificacoes"] for row in body) == 3


@requires_postgres_mvs
def test_curva_epidemica_honours_shared_filters(_notificacoes_db_harness):
    h = _notificacoes_db_harness
    _seed_curva_epidemica_rows(h)

    with _client(h) as c:
        response = c.get(
            "/notificacoes/curva-epidemica",
            params={"agravo": "ANIM", "ano_inicio": 2023, "ano_fim": 2023},
        )

    assert response.status_code == 200, response.text
    body = response.json()
    assert sum(row["total_notificacoes"] for row in body) == 0


# ---------------------------------------------------------------------------
# GET /notificacoes/breakdown
# ---------------------------------------------------------------------------


def _seed_breakdown_rows(h):
    """Seed rows spanning the agravo/campo compatibility matrix: DENG
    classi_fin rows (including an unmapped code), CHIK gravidade rows
    (including a NULL bucket), ANIM tra_classi/tp_acidente rows (including
    an unmapped tp_acidente code), and faixa_etaria/sexo variation across
    agravos.
    """
    DimTempo = h["DimTempo"]
    DimLocal = h["DimLocal"]
    DimAgravo = h["DimAgravo"]
    DimFaixaEtaria = h["DimFaixaEtaria"]
    FatoNotificacoes = h["FatoNotificacoes"]
    insert = h["insert"]

    dim_tempo_rows = [{"ano": 2023, "mes": None, "trimestre": None, "semestre": None}]
    dim_local_rows = [
        {
            **_MUNICIPIOS[0],
            "valid_from": datetime.date(2020, 1, 1),
            "is_current": True,
            "ativo": True,
            "codigo_sucessor": None,
        }
    ]
    dim_agravo_rows = [{"codigo": a, "descricao": a} for a in _AGRAVOS]
    dim_faixa_rows = list(_FAIXAS)

    rows_spec = [
        # DENG classi_fin rows, including an unmapped code (99).
        {
            "agravo": "DENG",
            "classi_fin": 10,
            "gravidade_grave": False,
            "tra_classi": None,
            "tp_acidente": None,
            "sexo": "M",
            "faixa": "20-29",
        },
        {
            "agravo": "DENG",
            "classi_fin": 10,
            "gravidade_grave": False,
            "tra_classi": None,
            "tp_acidente": None,
            "sexo": "M",
            "faixa": "20-29",
        },
        {
            "agravo": "DENG",
            "classi_fin": 5,
            "gravidade_grave": None,
            "tra_classi": None,
            "tp_acidente": None,
            "sexo": "F",
            "faixa": "30-39",
        },
        {
            "agravo": "DENG",
            "classi_fin": 99,
            "gravidade_grave": None,
            "tra_classi": None,
            "tp_acidente": None,
            "sexo": "F",
            "faixa": "30-39",
        },
        # CHIK gravidade rows, including a NULL (Ignorado) bucket.
        {
            "agravo": "CHIK",
            "classi_fin": 13,
            "gravidade_grave": True,
            "tra_classi": None,
            "tp_acidente": None,
            "sexo": "M",
            "faixa": "20-29",
        },
        {
            "agravo": "CHIK",
            "classi_fin": 13,
            "gravidade_grave": False,
            "tra_classi": None,
            "tp_acidente": None,
            "sexo": "F",
            "faixa": "30-39",
        },
        {
            "agravo": "CHIK",
            "classi_fin": 13,
            "gravidade_grave": None,
            "tra_classi": None,
            "tp_acidente": None,
            "sexo": None,
            "faixa": "20-29",
        },
        # ANIM tra_classi/tp_acidente rows, including an unmapped tp_acidente code (99).
        {
            "agravo": "ANIM",
            "classi_fin": None,
            "gravidade_grave": None,
            "tra_classi": 1,
            "tp_acidente": 3,
            "sexo": "M",
            "faixa": "20-29",
        },
        {
            "agravo": "ANIM",
            "classi_fin": None,
            "gravidade_grave": None,
            "tra_classi": 2,
            "tp_acidente": 99,
            "sexo": "F",
            "faixa": "30-39",
        },
    ]

    async def _seed_async():
        async with h["session_factory"]() as session:
            await session.execute(insert(DimTempo), dim_tempo_rows)
            await session.execute(insert(DimLocal), dim_local_rows)
            await session.execute(insert(DimAgravo), dim_agravo_rows)
            await session.execute(insert(DimFaixaEtaria), dim_faixa_rows)
            await session.commit()

            tempo_id = (
                (await session.execute(DimTempo.select())).mappings().all()[0]["id"]
            )
            local_id = (
                (await session.execute(DimLocal.select())).mappings().all()[0]["id"]
            )
            agravo_rows = (await session.execute(DimAgravo.select())).mappings().all()
            agravo_id_by_codigo = {r["codigo"]: r["id"] for r in agravo_rows}
            faixa_rows = (
                (await session.execute(DimFaixaEtaria.select())).mappings().all()
            )
            faixa_id_by_codigo = {r["codigo"]: r["id"] for r in faixa_rows}

            insert_rows = [
                {
                    "id": i + 1,
                    "dim_tempo_id": tempo_id,
                    "dim_local_id": local_id,
                    "dim_agravo_id": agravo_id_by_codigo[spec["agravo"]],
                    "dim_faixa_etaria_id": faixa_id_by_codigo[spec["faixa"]],
                    "tipo_agravo": spec["agravo"],
                    "numero_notificacao": f"BRK{i:03d}",
                    "notificacoes": 1,
                    "taxa_por_100k": 1.0,
                    "sexo": spec["sexo"],
                    "idade_anos": 25,
                    "classi_fin": spec["classi_fin"],
                    "gravidade_grave": spec["gravidade_grave"],
                    "tra_classi": spec["tra_classi"],
                    "tp_acidente": spec["tp_acidente"],
                    "dt_notific": datetime.date(2023, 1, 10),
                }
                for i, spec in enumerate(rows_spec)
            ]
            await session.execute(insert(FatoNotificacoes), insert_rows)
            await session.commit()

    asyncio.run(_seed_async())


def test_breakdown_sample_mode_503(client):
    response = client.get("/notificacoes/breakdown", params={"campo": "sexo"})
    assert response.status_code == 503


def test_breakdown_rejects_invalid_campo(_notificacoes_db_harness):
    h = _notificacoes_db_harness
    with _client(h) as c:
        response = c.get("/notificacoes/breakdown", params={"campo": "bogus"})
    assert response.status_code == 422


@requires_postgres_mvs
def test_breakdown_classi_fin_deng(_notificacoes_db_harness):
    h = _notificacoes_db_harness
    _seed_breakdown_rows(h)

    with _client(h) as c:
        response = c.get(
            "/notificacoes/breakdown", params={"campo": "classi_fin", "agravo": "DENG"}
        )

    assert response.status_code == 200, response.text
    body = response.json()
    by_codigo = {row["codigo"]: row for row in body}
    assert by_codigo[10]["categoria"] == "Dengue"
    assert by_codigo[10]["total_notificacoes"] == 2
    assert by_codigo[5]["categoria"] == "Descartado"
    assert "documentado" in by_codigo[99]["categoria"].lower()


def test_breakdown_classi_fin_rejects_anim(_notificacoes_db_harness):
    h = _notificacoes_db_harness
    _seed_breakdown_rows(h)

    with _client(h) as c:
        response = c.get(
            "/notificacoes/breakdown", params={"campo": "classi_fin", "agravo": "ANIM"}
        )

    assert response.status_code == 422, response.text
    detail = response.json()["detail"]
    assert isinstance(detail, str) and len(detail) > 0


def test_breakdown_tra_classi_rejects_deng(_notificacoes_db_harness):
    h = _notificacoes_db_harness
    _seed_breakdown_rows(h)

    with _client(h) as c:
        response = c.get(
            "/notificacoes/breakdown", params={"campo": "tra_classi", "agravo": "DENG"}
        )

    assert response.status_code == 422, response.text


def test_breakdown_requires_agravo_for_scoped_fields(_notificacoes_db_harness):
    h = _notificacoes_db_harness
    _seed_breakdown_rows(h)

    with _client(h) as c:
        response = c.get("/notificacoes/breakdown", params={"campo": "gravidade"})

    assert response.status_code == 422, response.text


@requires_postgres_mvs
def test_breakdown_gravidade_chik_includes_ignorado(_notificacoes_db_harness):
    h = _notificacoes_db_harness
    _seed_breakdown_rows(h)

    with _client(h) as c:
        response = c.get(
            "/notificacoes/breakdown", params={"campo": "gravidade", "agravo": "CHIK"}
        )

    assert response.status_code == 200, response.text
    body = response.json()
    categorias = {row["categoria"] for row in body}
    assert categorias == {"Grave", "Não grave", "Ignorado"}


@requires_postgres_mvs
def test_breakdown_faixa_etaria_any_agravo_ordered_by_ordem(_notificacoes_db_harness):
    h = _notificacoes_db_harness
    _seed_breakdown_rows(h)

    with _client(h) as c:
        response = c.get("/notificacoes/breakdown", params={"campo": "faixa_etaria"})

    assert response.status_code == 200, response.text
    body = response.json()
    assert len(body) > 0
    ordem_by_codigo = {"20-29": 5, "30-39": 6}
    codigos = [row["codigo"] for row in body]
    assert codigos == sorted(codigos, key=lambda c: ordem_by_codigo[c])


@requires_postgres_mvs
def test_breakdown_sexo_any_agravo_includes_ignorado(_notificacoes_db_harness):
    h = _notificacoes_db_harness
    _seed_breakdown_rows(h)

    with _client(h) as c:
        response = c.get("/notificacoes/breakdown", params={"campo": "sexo"})

    assert response.status_code == 200, response.text
    body = response.json()
    categorias = {row["categoria"] for row in body}
    assert "Ignorado" in categorias


@requires_postgres_mvs
def test_breakdown_tp_acidente_unmapped_code(_notificacoes_db_harness):
    h = _notificacoes_db_harness
    _seed_breakdown_rows(h)

    with _client(h) as c:
        response = c.get(
            "/notificacoes/breakdown", params={"campo": "tp_acidente", "agravo": "ANIM"}
        )

    assert response.status_code == 200, response.text
    body = response.json()
    by_codigo = {row["codigo"]: row for row in body}
    assert by_codigo[3]["categoria"] == "Escorpião"
    assert "documentado" in by_codigo[99]["categoria"].lower()


@requires_postgres_mvs
def test_breakdown_ordered_by_descending_total(_notificacoes_db_harness):
    h = _notificacoes_db_harness
    _seed_breakdown_rows(h)

    with _client(h) as c:
        response = c.get(
            "/notificacoes/breakdown", params={"campo": "classi_fin", "agravo": "DENG"}
        )

    assert response.status_code == 200, response.text
    body = response.json()
    totals = [row["total_notificacoes"] for row in body]
    assert totals == sorted(totals, reverse=True)


@requires_postgres_mvs
def test_breakdown_never_exposes_casos_vocabulary(_notificacoes_db_harness):
    h = _notificacoes_db_harness
    _seed_breakdown_rows(h)

    with _client(h) as c:
        response = c.get("/notificacoes/breakdown", params={"campo": "sexo"})

    assert response.status_code == 200, response.text
    body = response.json()
    for row in body:
        assert "casos" not in row
        assert "total_notificacoes" in row


# The tests below cover the paths that read fato_notificacoes directly, so they
# run on the SQLite harness. /municipio-summary and /curva-epidemica (beyond
# request validation) always read materialized views and stay covered only by
# the @requires_postgres_mvs tests above.


def test_uf_summary_classi_fin_filter_uses_fact_table(_notificacoes_db_harness):
    # classi_fin is not a column of mv_uf_summary_anual, so this request takes
    # the fact-table path.
    h = _notificacoes_db_harness
    facts = _seed_notificacoes(h)

    expected: dict[tuple[str, int], int] = {}
    for f in facts:
        if f["agravo"] == "DENG" and f["classi_fin"] == 10:
            key = (f["sigla_uf"], f["ano"])
            expected[key] = expected.get(key, 0) + 1

    with _client(h) as c:
        response = c.get(
            "/notificacoes/uf-summary", params={"agravo": "DENG", "classi_fin": 10}
        )

    assert response.status_code == 200, response.text
    body = response.json()
    assert {(r["sigla_uf"], r["ano"]): r["total_notificacoes"] for r in body} == (
        expected
    )
    assert all(r["agravo"] == "DENG" for r in body)
    assert all(r["codigo_ibge"] is None for r in body)
    assert all(r["taxa_por_100k"] is None or r["taxa_por_100k"] > 0 for r in body)


def test_uf_summary_municipio_filter_uses_fact_table(_notificacoes_db_harness):
    h = _notificacoes_db_harness
    facts = _seed_notificacoes(h)
    expected_total = sum(1 for f in facts if f["codigo_ibge_6"] == "330455")

    with _client(h) as c:
        response = c.get("/notificacoes/uf-summary", params={"municipio": "330455"})

    assert response.status_code == 200, response.text
    body = response.json()
    assert {r["sigla_uf"] for r in body} == {"RJ"}
    assert sum(r["total_notificacoes"] for r in body) == expected_total


def test_curva_epidemica_rejects_classi_fin(_notificacoes_db_harness):
    h = _notificacoes_db_harness

    with _client(h) as c:
        response = c.get(
            "/notificacoes/curva-epidemica", params={"agravo": "DENG", "classi_fin": 10}
        )

    assert response.status_code == 422
    assert "classi_fin" in response.json()["detail"]


def test_breakdown_sexo_municipio_filter_uses_fact_table(_notificacoes_db_harness):
    # mv_breakdown_anual has no município grain, so a municipio filter takes the
    # fact-table path.
    h = _notificacoes_db_harness
    facts = _seed_notificacoes(h)
    rows = [f for f in facts if f["codigo_ibge_6"] == "355030"]
    expected = {
        "Masculino": sum(1 for f in rows if f["sexo"] == "M"),
        "Feminino": sum(1 for f in rows if f["sexo"] == "F"),
    }

    with _client(h) as c:
        response = c.get(
            "/notificacoes/breakdown", params={"campo": "sexo", "municipio": "355030"}
        )

    assert response.status_code == 200, response.text
    body = response.json()
    assert {r["categoria"]: r["total_notificacoes"] for r in body} == expected
    assert all(r["campo"] == "sexo" for r in body)
    totals = [r["total_notificacoes"] for r in body]
    assert totals == sorted(totals, reverse=True)


def test_breakdown_faixa_etaria_municipio_filter_ordered_by_ordem(
    _notificacoes_db_harness,
):
    h = _notificacoes_db_harness
    facts = _seed_notificacoes(h)
    rows = [f for f in facts if f["codigo_ibge_6"] == "355100"]

    with _client(h) as c:
        response = c.get(
            "/notificacoes/breakdown",
            params={"campo": "faixa_etaria", "municipio": "355100"},
        )

    assert response.status_code == 200, response.text
    body = response.json()
    assert [r["codigo"] for r in body] == ["20-29", "30-39"]
    assert sum(r["total_notificacoes"] for r in body) == len(rows)


def test_breakdown_classi_fin_municipio_filter_decodes_categories(
    _notificacoes_db_harness,
):
    h = _notificacoes_db_harness
    facts = _seed_notificacoes(h)
    rows = [
        f for f in facts if f["codigo_ibge_6"] == "355030" and f["agravo"] == "DENG"
    ]
    expected_codigos = {f["classi_fin"] for f in rows}

    with _client(h) as c:
        response = c.get(
            "/notificacoes/breakdown",
            params={"campo": "classi_fin", "agravo": "DENG", "municipio": "355030"},
        )

    assert response.status_code == 200, response.text
    body = response.json()
    assert {r["codigo"] for r in body} == expected_codigos
    assert sum(r["total_notificacoes"] for r in body) == len(rows)
    assert all(r["categoria"] for r in body)


@pytest.mark.parametrize(
    ("campo", "agravo"),
    [("gravidade", "CHIK"), ("tra_classi", "ANIM"), ("tp_acidente", "ANIM")],
)
def test_breakdown_agravo_scoped_campos_municipio_filter(
    _notificacoes_db_harness, campo, agravo
):
    h = _notificacoes_db_harness
    facts = _seed_notificacoes(h)
    rows = [
        f for f in facts if f["codigo_ibge_6"] == "330455" and f["agravo"] == agravo
    ]

    with _client(h) as c:
        response = c.get(
            "/notificacoes/breakdown",
            params={"campo": campo, "agravo": agravo, "municipio": "330455"},
        )

    assert response.status_code == 200, response.text
    body = response.json()
    assert sum(r["total_notificacoes"] for r in body) == len(rows)
    assert all(r["campo"] == campo and r["categoria"] for r in body)
