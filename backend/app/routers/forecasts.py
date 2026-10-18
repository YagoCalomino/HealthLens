from __future__ import annotations

from collections import defaultdict

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import (
    Column,
    MetaData,
    Numeric,
    SmallInteger,
    String,
    Table,
    func,
    or_,
    select,
)
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db import get_db
from app.models.dimensions import DimLocal
from app.models.ml_results import ForecastResultados
from app.schemas.forecasts import (
    ForecastResponse,
    HistoricoItem,
    ModeloDetalhe,
    MunicipioInfo,
    PrevisaoItem,
)

# Raw Table — attached to private MetaData, intentionally excluded from Alembic autogenerate.
# If mv_taxa_municipio_ano view definition changes, update this Table manually.
_metadata = MetaData()

mv_taxa_municipio_ano = Table(
    "mv_taxa_municipio_ano",
    _metadata,
    Column("codigo_ibge_6", String(6)),
    Column("codigo_ibge_7", String(7)),
    Column("nome_municipio", String(100)),
    Column("sigla_uf", String(2)),
    Column("regiao", String(20)),
    Column("ano", SmallInteger),
    Column("total_eventos", Numeric),
    Column("populacao_municipio", Numeric),
    Column("taxa_por_100k", Numeric(10, 4)),
    Column("fonte", String(3)),
)

# Maps known metric names to their source system.
# Used by Query 4 to filter mv_taxa_municipio_ano by the correct fonte value.
# Without this, SIH-derived metrics (taxa_internacao_100k) would always return
# an empty historico because the view stores SIH rows under fonte='SIH', not 'SIM'.
METRICA_FONTE: dict[str, str] = {
    "taxa_mortalidade_100k": "SIM",
    "taxa_internacao_100k": "SIH",
}

router = APIRouter(prefix="/forecasts", tags=["forecasts"])


@router.get("/", response_model=ForecastResponse)
async def obter_forecast(
    db: AsyncSession | None = Depends(get_db),
    municipio: str | None = Query(default=None, max_length=6),
    uf: str | None = Query(default=None, max_length=2),
    metrica: str = Query(default="taxa_mortalidade_100k", max_length=30),
) -> ForecastResponse:
    if settings.sample_mode:
        raise HTTPException(status_code=503, detail="Not available in sample mode")
    if db is None:
        raise HTTPException(status_code=503, detail="Not available in sample mode")
    if municipio is None and uf is None:
        raise HTTPException(
            status_code=400, detail="municipio or uf parameter is required"
        )

    if uf is not None and municipio is None:
        # UF-only path: resolve representative dim_local row by sigla_uf.
        # Uses ORDER BY id LIMIT 1 to match ML runner's DISTINCT ON (codigo_uf) ORDER BY id logic.
        result_uf_row = await db.execute(
            select(DimLocal.id, DimLocal.codigo_uf, DimLocal.sigla_uf)
            .where(DimLocal.sigla_uf == uf)
            .where(DimLocal.is_current == True)  # noqa: E712
            .order_by(DimLocal.id)
            .limit(1)
        )
        uf_row = result_uf_row.one_or_none()
        if uf_row is None:
            raise HTTPException(status_code=404, detail="UF não encontrada")

        uf_dim_local_id = uf_row.id

        uf_clause = (ForecastResultados.dim_local_id == uf_dim_local_id) & (
            ForecastResultados.granularidade == "uf"
        )

        forecast_query = (
            select(
                ForecastResultados.granularidade,
                ForecastResultados.ano_forecast,
                ForecastResultados.valor_previsto,
                ForecastResultados.intervalo_inferior_80,
                ForecastResultados.intervalo_superior_80,
                ForecastResultados.intervalo_inferior_95,
                ForecastResultados.intervalo_superior_95,
                ForecastResultados.mase,
                ForecastResultados.smape,
                ForecastResultados.modelo_utilizado,
                ForecastResultados.ano_referencia,
            )
            .where(uf_clause)
            .where(ForecastResultados.metrica == metrica)
            .where(ForecastResultados.dim_causa_id == None)  # noqa: E711
            .order_by(
                ForecastResultados.modelo_utilizado, ForecastResultados.ano_forecast
            )
        )

        result_forecast = await db.execute(forecast_query)
        rows = result_forecast.fetchall()

        if not rows:
            raise HTTPException(
                status_code=404,
                detail="Nenhuma previsão encontrada para a UF solicitada",
            )

        # All rows are granularidade='uf' — use them directly for ano_referencia.
        ano_referencia = max(r.ano_referencia for r in rows)

        modelo_rows: dict[tuple[str, str], list] = defaultdict(list)
        for row in rows:
            modelo_rows[(row.granularidade, row.modelo_utilizado)].append(row)

        modelos: dict[str, ModeloDetalhe] = {}
        for (granularidade, modelo_nome), m_rows in modelo_rows.items():  # noqa: F841
            key = modelo_nome
            previsoes = [
                PrevisaoItem(
                    ano=r.ano_forecast,
                    valor_previsto=float(r.valor_previsto),
                    ci80_inf=float(r.intervalo_inferior_80)
                    if r.intervalo_inferior_80 is not None
                    else None,
                    ci80_sup=float(r.intervalo_superior_80)
                    if r.intervalo_superior_80 is not None
                    else None,
                    ci95_inf=float(r.intervalo_inferior_95)
                    if r.intervalo_inferior_95 is not None
                    else None,
                    ci95_sup=float(r.intervalo_superior_95)
                    if r.intervalo_superior_95 is not None
                    else None,
                )
                for r in sorted(m_rows, key=lambda x: x.ano_forecast)
            ]
            modelos[key] = ModeloDetalhe(
                mase=float(m_rows[0].mase) if m_rows[0].mase is not None else None,
                smape=float(m_rows[0].smape) if m_rows[0].smape is not None else None,
                previsoes=previsoes,
            )

        # mv_taxa_municipio_ano is municipality-keyed; historico is not available at UF level.
        return ForecastResponse(
            municipio=MunicipioInfo(
                codigo_ibge_6="",
                nome_municipio=uf,
                sigla_uf=uf,
            ),
            metrica=metrica,
            ano_referencia=ano_referencia,
            historico=[],
            modelos=modelos,
        )

    # municipio path — unchanged from original implementation
    if municipio is not None:
        # Query 1: resolve dim_local row for the requested municipality
        result = await db.execute(
            select(
                DimLocal.id,
                DimLocal.codigo_uf,
                DimLocal.nome_municipio,
                DimLocal.sigla_uf,
            )
            .where(DimLocal.codigo_ibge_6 == municipio)
            .where(DimLocal.is_current == True)  # noqa: E712
            .limit(1)
        )
        local_row = result.one_or_none()
        if local_row is None:
            raise HTTPException(status_code=404, detail="Município não encontrado")

        municipio_dim_local_id = local_row.id
        codigo_uf = local_row.codigo_uf

        # Query 2: resolve UF representative — lowest-id municipality in the same UF.
        # ML runner uses DISTINCT ON (codigo_uf) ORDER BY codigo_uf, id which yields MIN(id).
        result_uf = await db.execute(
            select(func.min(DimLocal.id).label("uf_dim_local_id"))
            .where(DimLocal.codigo_uf == codigo_uf)
            .where(DimLocal.is_current == True)  # noqa: E712
        )
        uf_dim_local_id = result_uf.scalar_one_or_none()

        # Query 3: fetch forecast rows for both municipio and UF (Prophet) granularidades
        municipio_clause = (
            ForecastResultados.dim_local_id == municipio_dim_local_id
        ) & (ForecastResultados.granularidade == "municipio")
        if uf_dim_local_id is not None:
            uf_clause = (ForecastResultados.dim_local_id == uf_dim_local_id) & (
                ForecastResultados.granularidade == "uf"
            )
            where_clause = or_(municipio_clause, uf_clause)
        else:
            where_clause = municipio_clause

        forecast_query = (
            select(
                ForecastResultados.granularidade,  # needed to isolate municipio rows for ano_referencia
                ForecastResultados.ano_forecast,
                ForecastResultados.valor_previsto,
                ForecastResultados.intervalo_inferior_80,
                ForecastResultados.intervalo_superior_80,
                ForecastResultados.intervalo_inferior_95,
                ForecastResultados.intervalo_superior_95,
                ForecastResultados.mase,
                ForecastResultados.smape,
                ForecastResultados.modelo_utilizado,
                ForecastResultados.ano_referencia,
            )
            .where(where_clause)
            .where(ForecastResultados.metrica == metrica)
            .where(ForecastResultados.dim_causa_id == None)  # noqa: E711
            .order_by(
                ForecastResultados.modelo_utilizado, ForecastResultados.ano_forecast
            )
        )

        result_forecast = await db.execute(forecast_query)
        rows = result_forecast.fetchall()

        if not rows:
            raise HTTPException(
                status_code=404,
                detail="Nenhuma previsão encontrada para o município solicitado",
            )

        # Derive ano_referencia only from municipio-granularidade rows to avoid UF runs
        # shifting the reference year. If no municipio rows exist, fall back to all rows.
        municipio_rows = [r for r in rows if r.granularidade == "municipio"]
        if municipio_rows:
            ano_referencia = max(r.ano_referencia for r in municipio_rows)
        else:
            ano_referencia = max(r.ano_referencia for r in rows)

        # Group forecast rows by (granularidade, modelo_utilizado) to avoid conflating
        # municipio-level and UF-level forecasts that share the same modelo_utilizado name.
        modelo_rows_m: dict[tuple[str, str], list] = defaultdict(list)
        for row in rows:
            modelo_rows_m[(row.granularidade, row.modelo_utilizado)].append(row)

        modelos_m: dict[str, ModeloDetalhe] = {}
        for (granularidade, modelo_nome), m_rows in modelo_rows_m.items():  # noqa: F841
            key = modelo_nome
            previsoes = [
                PrevisaoItem(
                    ano=r.ano_forecast,
                    valor_previsto=float(r.valor_previsto),
                    ci80_inf=float(r.intervalo_inferior_80)
                    if r.intervalo_inferior_80 is not None
                    else None,
                    ci80_sup=float(r.intervalo_superior_80)
                    if r.intervalo_superior_80 is not None
                    else None,
                    ci95_inf=float(r.intervalo_inferior_95)
                    if r.intervalo_inferior_95 is not None
                    else None,
                    ci95_sup=float(r.intervalo_superior_95)
                    if r.intervalo_superior_95 is not None
                    else None,
                )
                for r in sorted(m_rows, key=lambda x: x.ano_forecast)
            ]
            # mase/smape are stored per series, same value across all year rows for a model
            modelos_m[key] = ModeloDetalhe(
                mase=float(m_rows[0].mase) if m_rows[0].mase is not None else None,
                smape=float(m_rows[0].smape) if m_rows[0].smape is not None else None,
                previsoes=previsoes,
            )

        # Query 4: historico from mv_taxa_municipio_ano, filtered by the correct fonte for this metrica.
        # METRICA_FONTE maps each metric to its source system (SIM or SIH).
        # Without this, taxa_internacao_100k (SIH) would always return empty historico.
        fonte_hist = METRICA_FONTE.get(
            metrica, "SIM"
        )  # default to SIM for unknown metrics
        mv = mv_taxa_municipio_ano
        result_hist = await db.execute(
            select(mv.c.ano, mv.c.taxa_por_100k.label("valor"))
            .where(mv.c.codigo_ibge_6 == municipio)
            .where(mv.c.fonte == fonte_hist)
            .where(mv.c.ano <= ano_referencia)
            .order_by(mv.c.ano)
        )
        historico = [
            HistoricoItem(
                ano=r.ano, valor=float(r.valor) if r.valor is not None else None
            )
            for r in result_hist.fetchall()
        ]

        return ForecastResponse(
            municipio=MunicipioInfo(
                codigo_ibge_6=municipio,
                nome_municipio=local_row.nome_municipio,
                sigla_uf=local_row.sigla_uf,
            ),
            metrica=metrica,
            ano_referencia=ano_referencia,
            historico=historico,
            modelos=modelos_m,
        )

    # Should be unreachable — dual-None guard above prevents both being None.
    raise HTTPException(status_code=400, detail="municipio or uf parameter is required")
