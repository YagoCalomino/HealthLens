from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi_pagination.cursor import CursorPage, CursorParams
from fastapi_pagination.customization import CustomizedPage, UseParamsFields
from fastapi_pagination.ext.sqlalchemy import paginate
from sqlalchemy import (
    Column,
    MetaData,
    Numeric,
    SmallInteger,
    String,
    Table,
    func,
    literal,
    select,
)
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db import get_db
from app.models.dimensions import DimCausa, DimFaixaEtaria, DimLocal, DimTempo
from app.models.facts import FatoInternacoes, FatoObitos
from app.schemas.indicadores import IndicadorResponse


# The library default (50, max 100) made a UF drill-down walk ~125 pages for
# BA (417 municípios × 15 anos); 1000 cuts that to ~7 round trips. Customized on
# the page type (not a CursorParams subclass) because add_pagination validates
# the size query param against the response model's own params.
IndicadoresCursorPage = CustomizedPage[
    CursorPage[IndicadorResponse],
    UseParamsFields(size=Query(1000, ge=1, le=1000, description="Page size")),
]
IndicadoresCursorParams = IndicadoresCursorPage.__params_type__


_metadata = MetaData()

mv_taxa_uf_ano = Table(
    "mv_taxa_uf_ano",
    _metadata,
    Column("sigla_uf", String(2)),
    Column("ano", SmallInteger),
    Column("total_eventos", Numeric),
    Column("populacao_uf", Numeric),
    Column("taxa_por_100k", Numeric(10, 4)),
    Column("fonte", String(3)),
)

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

router = APIRouter(prefix="/indicadores", tags=["indicadores"])


@router.get("/uf-summary", response_model=list[IndicadorResponse])
async def listar_indicadores_uf_summary(
    db: AsyncSession = Depends(get_db),
    uf: str | None = Query(default=None, max_length=2),
    fonte: Literal["SIM", "SIH"] | None = Query(default=None),
    ano_inicio: int | None = Query(default=None, ge=1990, le=2100),
    ano_fim: int | None = Query(default=None, ge=1990, le=2100),
) -> list[IndicadorResponse]:
    """All UF-year rows without pagination (~400 rows max). Used by national choropleth and UF time-series."""
    if settings.sample_mode:
        raise HTTPException(status_code=503, detail="Not available in sample mode")

    mv = mv_taxa_uf_ano
    query = select(
        mv.c.sigla_uf,
        literal(None).label("codigo_ibge"),
        literal(None).label("nome_municipio"),
        mv.c.ano,
        mv.c.total_eventos,
        mv.c.populacao_uf.label("populacao"),
        mv.c.taxa_por_100k,
        mv.c.fonte,
    )
    if uf:
        query = query.where(mv.c.sigla_uf == uf.upper())
    if fonte:
        query = query.where(mv.c.fonte == fonte.upper())
    if ano_inicio:
        query = query.where(mv.c.ano >= ano_inicio)
    if ano_fim:
        query = query.where(mv.c.ano <= ano_fim)
    query = query.order_by(mv.c.sigla_uf, mv.c.ano, mv.c.fonte)

    result = await db.execute(query)
    rows = result.mappings().all()
    return [IndicadorResponse(**dict(r)) for r in rows]


@router.get("/", response_model=IndicadoresCursorPage)
async def listar_indicadores(
    db: AsyncSession | None = Depends(get_db),
    params: CursorParams = Depends(IndicadoresCursorParams),
    uf: str | None = Query(default=None, max_length=2),
    municipio: str | None = Query(default=None, max_length=6),
    fonte: Literal["SIM", "SIH"] | None = Query(default=None),
    cid_capitulo: str | None = Query(default=None),
    cid_grupo: str | None = Query(default=None),
    cid_codigo: str | None = Query(default=None, max_length=5),
    faixa_etaria: str | None = Query(default=None),
    sexo: str | None = Query(default=None, max_length=1),
    ano_inicio: int | None = Query(default=None, ge=1990, le=2100),
    ano_fim: int | None = Query(default=None, ge=1990, le=2100),
    nivel: str = Query(default="uf", pattern="^(uf|municipio)$"),
):
    if settings.sample_mode:
        raise HTTPException(status_code=503, detail="Not available in sample mode")
    assert db is not None  # get_db only yields None in SAMPLE_MODE, guarded above

    # Routing decision evaluated before any query construction.
    # Fast path: materialized views (no CID / demographic filters active).
    # Slow path: fact table JOINs (at least one of cid_* / faixa_etaria / sexo is set).
    use_fast_path = not any([cid_capitulo, cid_grupo, cid_codigo, faixa_etaria, sexo])

    if use_fast_path:
        if municipio is not None or nivel == "municipio":
            # Municipality-level fast path — mv_taxa_municipio_ano.
            # Entered when a specific municipio is requested (exact match on codigo_ibge_6)
            # OR when nivel='municipio' (all municipalities in the given UF, for choropleth
            # and DataTable when the user has drilled into a UF without selecting one municipality).
            mv = mv_taxa_municipio_ano
            query = select(
                mv.c.sigla_uf,
                mv.c.codigo_ibge_7.label("codigo_ibge"),
                mv.c.nome_municipio,
                mv.c.ano,
                mv.c.total_eventos,
                mv.c.populacao_municipio.label("populacao"),
                mv.c.taxa_por_100k,
                mv.c.fonte,
            )
            if municipio:
                query = query.where(mv.c.codigo_ibge_6 == municipio)
            if uf:
                query = query.where(mv.c.sigla_uf == uf.upper())
            if fonte:
                query = query.where(mv.c.fonte == fonte.upper())
            if ano_inicio:
                query = query.where(mv.c.ano >= ano_inicio)
            if ano_fim:
                query = query.where(mv.c.ano <= ano_fim)
            query = query.order_by(
                mv.c.sigla_uf, mv.c.ano, mv.c.fonte, mv.c.codigo_ibge_6
            )
        else:
            # UF-level fast path — mv_taxa_uf_ano
            mv = mv_taxa_uf_ano
            query = select(
                mv.c.sigla_uf,
                literal(None).label("codigo_ibge"),
                literal(None).label("nome_municipio"),
                mv.c.ano,
                mv.c.total_eventos,
                mv.c.populacao_uf.label("populacao"),
                mv.c.taxa_por_100k,
                mv.c.fonte,
            )
            if uf:
                query = query.where(mv.c.sigla_uf == uf.upper())
            if fonte:
                query = query.where(mv.c.fonte == fonte.upper())
            if ano_inicio:
                query = query.where(mv.c.ano >= ano_inicio)
            if ano_fim:
                query = query.where(mv.c.ano <= ano_fim)
            query = query.order_by(mv.c.sigla_uf, mv.c.ano, mv.c.fonte)
    else:
        # Slow path: JOIN fact table with dimensions
        if fonte == "SIH":
            FactTable = FatoInternacoes
            fact_col = FatoInternacoes.internacoes
            fonte_label = "SIH"
        else:
            FactTable = FatoObitos
            fact_col = FatoObitos.obitos
            fonte_label = "SIM"
        fonte_col = literal(fonte_label).label("fonte")

        query = (
            select(
                DimLocal.sigla_uf,
                DimLocal.codigo_ibge_7.label("codigo_ibge"),
                DimLocal.nome_municipio,
                DimTempo.ano,
                func.sum(fact_col).label("total_eventos"),
                literal(None).label("populacao"),
                literal(None).label("taxa_por_100k"),
                fonte_col,
            )
            .select_from(FactTable)
            .join(DimTempo, FactTable.dim_tempo_id == DimTempo.id)
            .join(DimLocal, FactTable.dim_local_id == DimLocal.id)
            .join(DimCausa, FactTable.dim_causa_id == DimCausa.id)
            .join(DimFaixaEtaria, FactTable.dim_faixa_etaria_id == DimFaixaEtaria.id)
        )
        if uf:
            query = query.where(DimLocal.sigla_uf == uf.upper())
        if municipio:
            query = query.where(DimLocal.codigo_ibge_6 == municipio)
        if cid_capitulo:
            query = query.where(DimCausa.capitulo == cid_capitulo)
        if cid_grupo:
            query = query.where(DimCausa.categoria == cid_grupo)
        if cid_codigo:
            query = query.where(DimCausa.codigo_cid10 == cid_codigo)
        if faixa_etaria:
            query = query.where(DimFaixaEtaria.codigo == faixa_etaria)
        if sexo:
            query = query.where(FactTable.sexo == sexo)
        if ano_inicio:
            query = query.where(DimTempo.ano >= ano_inicio)
        if ano_fim:
            query = query.where(DimTempo.ano <= ano_fim)
        query = query.group_by(
            DimLocal.sigla_uf,
            DimLocal.codigo_ibge_7,
            DimLocal.nome_municipio,
            DimTempo.ano,
        ).order_by(DimLocal.sigla_uf, DimTempo.ano, DimLocal.codigo_ibge_7)

    return await paginate(db, query, params)
