import asyncio
import datetime

import pytest


def test_forecasts_sample_mode_503(client):
    response = client.get("/forecasts")
    assert response.status_code == 503


def test_forecasts_missing_municipio_400(client):
    # When SAMPLE_MODE=true (conftest default), 503 fires before 400.
    # 400 is gated behind DB; testable only with DB available.
    # In sample mode, 503 fires first — accept either status in CI.
    response = client.get("/forecasts")
    assert response.status_code in (400, 503)


def test_openapi_schema_forecasts(client):
    response = client.get("/openapi.json")
    assert response.status_code == 200
    paths = response.json()["paths"]
    # FastAPI registers prefix="/forecasts" + route="/" as "/forecasts/" in OpenAPI
    assert any(p.startswith("/forecasts") for p in paths)


@pytest.fixture
def _forecast_db_harness(monkeypatch):
    """Isolated in-memory SQLite override for DB-backed forecasts router coverage.

    Mirrors the harness in test_routers_indicadores.py:
    test_uf_pagination_no_dup_or_skip_across_sources — module-level import
    of settings/get_db through the router module itself (not fresh `from
    app.config import ...`), since test_health.py's CORS-wildcard test purges
    app.main/app.config from sys.modules and re-imports them, leaving stale
    settings/get_db references otherwise.
    """
    from sqlalchemy import MetaData, insert
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
    from sqlalchemy.pool import StaticPool

    from app.main import app
    from app.models.dimensions import DimCausa, DimLocal
    from app.models.ml_results import ForecastResultados
    from app.routers import forecasts as forecasts_module

    settings = forecasts_module.settings
    get_db = forecasts_module.get_db
    mv_taxa_municipio_ano = forecasts_module.mv_taxa_municipio_ano

    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    # Only the tables this router touches need to exist against sqlite:
    # dim_local, dim_causa (FK target of forecast_resultados.dim_causa_id),
    # forecast_resultados (ORM-mapped) + mv_taxa_municipio_ano (raw Table).
    orm_metadata = MetaData()
    DimLocal.__table__.to_metadata(orm_metadata)
    DimCausa.__table__.to_metadata(orm_metadata)
    ForecastResultados.__table__.to_metadata(orm_metadata)
    mv_taxa_municipio_ano.to_metadata(orm_metadata)

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
        "ForecastResultados": ForecastResultados,
        "mv_taxa_municipio_ano": mv_taxa_municipio_ano,
        "app": app,
        "get_db": get_db,
    }

    app.dependency_overrides.pop(get_db, None)
    asyncio.run(engine.dispose())


def test_forecasts_municipio_returns_200_with_historico_and_ci(_forecast_db_harness):
    from fastapi.testclient import TestClient

    h = _forecast_db_harness
    DimLocal = h["DimLocal"]
    ForecastResultados = h["ForecastResultados"]
    mv = h["mv_taxa_municipio_ano"]
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
            result = await session.execute(
                DimLocal.__table__.select().where(DimLocal.codigo_ibge_6 == "355030")
            )
            dim_local_row = result.one()

            await session.execute(
                insert(ForecastResultados),
                [
                    {
                        "id": 1,
                        "dim_local_id": dim_local_row.id,
                        "dim_causa_id": None,
                        "granularidade": "municipio",
                        "metrica": "taxa_mortalidade_100k",
                        "ano_referencia": 2023,
                        "ano_forecast": 2024,
                        "valor_previsto": 12.5,
                        "intervalo_inferior_80": 10.0,
                        "intervalo_superior_80": 15.0,
                        "intervalo_inferior_95": 8.0,
                        "intervalo_superior_95": 17.0,
                        "mase": 0.5,
                        "smape": 0.1,
                        "modelo_utilizado": "AutoARIMA",
                    }
                ],
            )
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

    with TestClient(h["app"]) as local_client:
        response = local_client.get("/forecasts", params={"municipio": "355030"})

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["municipio"]["codigo_ibge_6"] == "355030"
    assert body["ano_referencia"] == 2023
    assert len(body["historico"]) == 1
    assert body["historico"][0]["valor"] == 10.0
    assert "AutoARIMA" in body["modelos"]
    previsao = body["modelos"]["AutoARIMA"]["previsoes"][0]
    assert previsao["ci80_inf"] == 10.0
    assert previsao["ci80_sup"] == 15.0
    assert previsao["ci95_inf"] == 8.0
    assert previsao["ci95_sup"] == 17.0


def test_forecasts_missing_municipio_400_db_available(_forecast_db_harness):
    from fastapi.testclient import TestClient

    h = _forecast_db_harness
    with TestClient(h["app"]) as local_client:
        response = local_client.get("/forecasts")

    assert response.status_code == 400
    assert "municipio or uf" in response.json()["detail"]


def test_forecasts_municipio_not_found_404(_forecast_db_harness):
    from fastapi.testclient import TestClient

    h = _forecast_db_harness
    with TestClient(h["app"]) as local_client:
        response = local_client.get("/forecasts", params={"municipio": "999999"})

    assert response.status_code == 404


def _seed_forecast_rows(h, forecast_rows):
    """Insert São Paulo into dim_local plus the given forecast_resultados rows
    (dim_local_id is filled in with São Paulo's id)."""
    DimLocal = h["DimLocal"]
    ForecastResultados = h["ForecastResultados"]
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
            result = await session.execute(
                DimLocal.__table__.select().where(DimLocal.codigo_ibge_6 == "355030")
            )
            dim_local_id = result.one().id
            if forecast_rows:
                await session.execute(
                    insert(ForecastResultados),
                    [{**row, "dim_local_id": dim_local_id} for row in forecast_rows],
                )
            await session.commit()

    asyncio.run(_seed())


def _uf_forecast_row(row_id, ano_forecast, valor):
    return {
        "id": row_id,
        "dim_causa_id": None,
        "granularidade": "uf",
        "metrica": "taxa_mortalidade_100k",
        "ano_referencia": 2023,
        "ano_forecast": ano_forecast,
        "valor_previsto": valor,
        "intervalo_inferior_80": valor - 2.0,
        "intervalo_superior_80": valor + 2.0,
        "intervalo_inferior_95": None,
        "intervalo_superior_95": None,
        "mase": 0.8,
        "smape": None,
        "modelo_utilizado": "Prophet",
    }


def test_forecasts_uf_returns_200_with_prophet_and_empty_historico(
    _forecast_db_harness,
):
    from fastapi.testclient import TestClient

    h = _forecast_db_harness
    # Inserted out of order to check the response is sorted by ano_forecast.
    _seed_forecast_rows(
        h, [_uf_forecast_row(1, 2025, 30.0), _uf_forecast_row(2, 2024, 20.0)]
    )

    with TestClient(h["app"]) as local_client:
        response = local_client.get("/forecasts", params={"uf": "SP"})

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["municipio"] == {
        "codigo_ibge_6": "",
        "nome_municipio": "SP",
        "sigla_uf": "SP",
    }
    assert body["ano_referencia"] == 2023
    # mv_taxa_municipio_ano is municipality-keyed, so the UF path has no historico.
    assert body["historico"] == []
    prophet = body["modelos"]["Prophet"]
    assert prophet["mase"] == 0.8
    assert prophet["smape"] is None
    assert [p["ano"] for p in prophet["previsoes"]] == [2024, 2025]
    assert prophet["previsoes"][0]["ci80_inf"] == 18.0
    assert prophet["previsoes"][0]["ci95_inf"] is None


def test_forecasts_uf_not_found_404(_forecast_db_harness):
    from fastapi.testclient import TestClient

    h = _forecast_db_harness
    with TestClient(h["app"]) as local_client:
        response = local_client.get("/forecasts", params={"uf": "SP"})

    assert response.status_code == 404
    assert response.json()["detail"] == "UF não encontrada"


def test_forecasts_uf_without_forecasts_404(_forecast_db_harness):
    from fastapi.testclient import TestClient

    h = _forecast_db_harness
    _seed_forecast_rows(h, [])

    with TestClient(h["app"]) as local_client:
        response = local_client.get("/forecasts", params={"uf": "SP"})

    assert response.status_code == 404
    assert "UF" in response.json()["detail"]


def test_forecasts_municipio_without_forecasts_404(_forecast_db_harness):
    from fastapi.testclient import TestClient

    h = _forecast_db_harness
    _seed_forecast_rows(h, [])

    with TestClient(h["app"]) as local_client:
        response = local_client.get("/forecasts", params={"municipio": "355030"})

    assert response.status_code == 404
    assert "município" in response.json()["detail"]
