def test_indicadores_no_filter_sample_mode_503(client):
    response = client.get("/indicadores")
    assert response.status_code == 503


def test_indicadores_filter_uf_sample_mode_503(client):
    response = client.get("/indicadores?uf=SP")
    assert response.status_code == 503


def test_indicadores_filter_cid_sample_mode_503(client):
    response = client.get("/indicadores?cid_capitulo=IX")
    assert response.status_code == 503


def test_uf_pagination_no_dup_or_skip_across_sources(monkeypatch):
    """Regression test: mv_taxa_uf_ano's unique index is
    (sigla_uf, ano, fonte). Once SIH rows exist alongside SIM rows for the
    same (sigla_uf, ano), a cursor sort key that omits fonte can skip or
    duplicate rows at page boundaries. This seeds both fonte values for the
    same (sigla_uf, ano) pairs and walks every page of GET /indicadores at
    nivel=uf with a small page size, asserting the full walk is lossless
    and duplicate-free.
    """
    import asyncio

    from fastapi.testclient import TestClient
    from sqlalchemy import MetaData, insert
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
    from sqlalchemy.pool import StaticPool

    from app.main import app
    from app.routers import indicadores as indicadores_module

    # Reference settings/get_db/mv_taxa_uf_ano through the indicadores router
    # module itself (not via fresh `from app.config import ...` / `from app.db
    # import ...` statements) — test_health.py's CORS-wildcard test purges
    # app.main/app.config from sys.modules and re-imports them, which would
    # otherwise leave this test patching a `settings` singleton that the
    # (unpurged, still-cached) indicadores module never reads.
    settings = indicadores_module.settings
    get_db = indicadores_module.get_db
    mv_taxa_uf_ano = indicadores_module.mv_taxa_uf_ano

    # Isolated in-memory SQLite engine — hermetic, no shared/live infrastructure
    # touched. StaticPool keeps the single in-memory connection alive across
    # every checkout so schema + seeded rows survive between requests.
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    # mv_taxa_uf_ano's Table is bound to its own MetaData() instance in the
    # router module — create only that table against the sqlite engine.
    table_metadata = MetaData()
    mv_taxa_uf_ano.to_metadata(table_metadata)

    expected_rows = []
    for sigla_uf in ("SP", "RJ"):
        for ano in (2020, 2021):
            for fonte in ("SIM", "SIH"):
                expected_rows.append(
                    {
                        "sigla_uf": sigla_uf,
                        "ano": ano,
                        "total_eventos": 100,
                        "populacao_uf": 1000,
                        "taxa_por_100k": 10.0,
                        "fonte": fonte,
                    }
                )
    expected_tuples = {(r["sigla_uf"], r["ano"], r["fonte"]) for r in expected_rows}
    assert (
        len(expected_tuples) == 8
    )  # 2 UFs x 2 anos x 2 fontes, no accidental collapse

    async def _setup():
        async with engine.begin() as conn:
            await conn.run_sync(table_metadata.create_all)
        async with session_factory() as session:
            await session.execute(insert(mv_taxa_uf_ano), expected_rows)
            await session.commit()

    asyncio.run(_setup())

    async def _override_get_db():
        async with session_factory() as session:
            yield session

    monkeypatch.setattr(settings, "sample_mode", False)
    app.dependency_overrides[get_db] = _override_get_db
    try:
        with TestClient(app) as local_client:
            collected: list[tuple[str, int, str]] = []
            cursor = None
            pages_walked = 0
            max_pages = 20  # guards against an infinite loop if pagination regresses (8 rows, size=1 => 8 pages expected)
            while True:
                # size=1 forces every page boundary to fall between two rows
                # that share (sigla_uf, ano) — the exact split point where an
                # ORDER BY missing fonte would skip or duplicate a row.
                params = {"nivel": "uf", "size": 1}
                if cursor:
                    params["cursor"] = cursor
                response = local_client.get("/indicadores", params=params)
                assert response.status_code == 200, response.text
                body = response.json()
                for item in body["items"]:
                    collected.append((item["sigla_uf"], item["ano"], item["fonte"]))
                pages_walked += 1
                assert pages_walked <= max_pages, "pagination did not terminate"
                cursor = body.get("next_page")
                if not cursor:
                    break
    finally:
        app.dependency_overrides.pop(get_db, None)
        asyncio.run(engine.dispose())

    # No skips: every expected tuple was returned.
    assert set(collected) == expected_tuples
    # No duplicates: every tuple was returned exactly once across the full walk.
    assert len(collected) == len(expected_tuples)


def _indicadores_db_harness(monkeypatch):
    """Isolated in-memory SQLite override shared by the additional filter-branch
    tests below. Reuses the exact override mechanics documented in
    test_uf_pagination_no_dup_or_skip_across_sources (module-level import
    through the router module itself, StaticPool, dependency_overrides
    popped + engine disposed in finally by the caller).
    """
    import asyncio

    from sqlalchemy import MetaData
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
    from sqlalchemy.pool import StaticPool

    from app.main import app
    from app.routers import indicadores as indicadores_module

    settings = indicadores_module.settings
    get_db = indicadores_module.get_db
    mv_taxa_uf_ano = indicadores_module.mv_taxa_uf_ano
    mv_taxa_municipio_ano = indicadores_module.mv_taxa_municipio_ano

    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    table_metadata = MetaData()
    mv_taxa_uf_ano.to_metadata(table_metadata)
    mv_taxa_municipio_ano.to_metadata(table_metadata)

    async def _setup():
        async with engine.begin() as conn:
            await conn.run_sync(table_metadata.create_all)

    asyncio.run(_setup())

    async def _override_get_db():
        async with session_factory() as session:
            yield session

    monkeypatch.setattr(settings, "sample_mode", False)
    app.dependency_overrides[get_db] = _override_get_db

    return {
        "app": app,
        "get_db": get_db,
        "engine": engine,
        "session_factory": session_factory,
        "mv_taxa_uf_ano": mv_taxa_uf_ano,
        "mv_taxa_municipio_ano": mv_taxa_municipio_ano,
    }


def test_indicadores_fonte_filter_uf_level(monkeypatch):
    """GET /indicadores?nivel=uf&fonte=SIM applies the fonte filter and returns
    only matching rows (mv_taxa_uf_ano fast path, lines 139-159)."""
    import asyncio

    from fastapi.testclient import TestClient
    from sqlalchemy import insert

    h = _indicadores_db_harness(monkeypatch)
    mv = h["mv_taxa_uf_ano"]

    async def _seed():
        async with h["session_factory"]() as session:
            await session.execute(
                insert(mv),
                [
                    {
                        "sigla_uf": "SP",
                        "ano": 2022,
                        "total_eventos": 100,
                        "populacao_uf": 1000,
                        "taxa_por_100k": 10.0,
                        "fonte": "SIM",
                    },
                    {
                        "sigla_uf": "SP",
                        "ano": 2022,
                        "total_eventos": 200,
                        "populacao_uf": 1000,
                        "taxa_por_100k": 20.0,
                        "fonte": "SIH",
                    },
                ],
            )
            await session.commit()

    asyncio.run(_seed())

    try:
        with TestClient(h["app"]) as local_client:
            response = local_client.get(
                "/indicadores", params={"nivel": "uf", "fonte": "SIM"}
            )
        assert response.status_code == 200, response.text
        body = response.json()
        assert len(body["items"]) == 1
        assert body["items"][0]["fonte"] == "SIM"
        assert body["items"][0]["codigo_ibge"] is None
    finally:
        h["app"].dependency_overrides.pop(h["get_db"], None)
        asyncio.run(h["engine"].dispose())


def test_indicadores_ano_range_narrows_time_series(monkeypatch):
    """ano_inicio/ano_fim narrow the mv_taxa_uf_ano time series (fast path)."""
    import asyncio

    from fastapi.testclient import TestClient
    from sqlalchemy import insert

    h = _indicadores_db_harness(monkeypatch)
    mv = h["mv_taxa_uf_ano"]

    async def _seed():
        async with h["session_factory"]() as session:
            await session.execute(
                insert(mv),
                [
                    {
                        "sigla_uf": "SP",
                        "ano": ano,
                        "total_eventos": 100,
                        "populacao_uf": 1000,
                        "taxa_por_100k": 10.0,
                        "fonte": "SIM",
                    }
                    for ano in (2019, 2020, 2021, 2022)
                ],
            )
            await session.commit()

    asyncio.run(_seed())

    try:
        with TestClient(h["app"]) as local_client:
            response = local_client.get(
                "/indicadores",
                params={"nivel": "uf", "ano_inicio": 2020, "ano_fim": 2021},
            )
        assert response.status_code == 200, response.text
        body = response.json()
        anos = {item["ano"] for item in body["items"]}
        assert anos == {2020, 2021}
    finally:
        h["app"].dependency_overrides.pop(h["get_db"], None)
        asyncio.run(h["engine"].dispose())


def test_indicadores_nivel_municipio_uses_fact_table_path(monkeypatch):
    """GET /indicadores?nivel=municipio exercises the municipality fast-path
    select (mv_taxa_municipio_ano) rather than mv_taxa_uf_ano — codigo_ibge is
    populated for municipality-level rows, unlike the UF-level None (IndicadorResponse.codigo_ibge
    is optional)."""
    import asyncio

    from fastapi.testclient import TestClient
    from sqlalchemy import insert

    h = _indicadores_db_harness(monkeypatch)
    mv = h["mv_taxa_municipio_ano"]

    async def _seed():
        async with h["session_factory"]() as session:
            await session.execute(
                insert(mv),
                [
                    {
                        "codigo_ibge_6": "355030",
                        "codigo_ibge_7": "3550308",
                        "nome_municipio": "Sao Paulo",
                        "sigla_uf": "SP",
                        "regiao": "Sudeste",
                        "ano": 2022,
                        "total_eventos": 100,
                        "populacao_municipio": 1000,
                        "taxa_por_100k": 10.0,
                        "fonte": "SIM",
                    }
                ],
            )
            await session.commit()

    asyncio.run(_seed())

    try:
        with TestClient(h["app"]) as local_client:
            response = local_client.get("/indicadores", params={"nivel": "municipio"})
        assert response.status_code == 200, response.text
        body = response.json()
        assert len(body["items"]) == 1
        item = body["items"][0]
        assert item["codigo_ibge"] == "3550308"
        assert item["nome_municipio"] == "Sao Paulo"
    finally:
        h["app"].dependency_overrides.pop(h["get_db"], None)
        asyncio.run(h["engine"].dispose())
