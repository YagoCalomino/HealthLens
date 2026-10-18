from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from fastapi_pagination.cursor import CursorPage, CursorParams
from fastapi_pagination.ext.sqlalchemy import paginate
from sqlalchemy import Column, MetaData, String, Table, literal, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db import get_db
from app.models.dimensions import DimLocal
from app.schemas.geo import MunicipioResponse, UFResponse

router = APIRouter(prefix="/geo", tags=["geo"])

# Minimal reference to mv_taxa_municipio_ano used only for the tem_dados EXISTS check.
# Full column set lives in indicadores.py; we only need codigo_ibge_6 here.
_geo_meta = MetaData()
_mv_taxa = Table("mv_taxa_municipio_ano", _geo_meta, Column("codigo_ibge_6", String(6)))


@router.get("/ufs", response_model=CursorPage[UFResponse])
async def listar_ufs(
    db: AsyncSession | None = Depends(get_db),
    params: CursorParams = Depends(),
):
    if settings.sample_mode:
        raise HTTPException(status_code=503, detail="Not available in sample mode")
    assert db is not None  # get_db only yields None in SAMPLE_MODE, guarded above

    # Labeled-column select with DISTINCT ON sigla_uf; transformer maps Row._mapping to UFResponse.
    # UFResponse fields (sigla, nome, codigo_ibge, codigo_topojson) differ from DimLocal column names,
    # so labeled select is required — from_attributes=True cannot bridge aliased field names.
    query = (
        select(
            DimLocal.sigla_uf.label("sigla"),
            DimLocal.nome_uf.label("nome"),
            DimLocal.codigo_uf.label("codigo_ibge"),
            DimLocal.sigla_uf.label("codigo_topojson"),
            DimLocal.id,
        )
        .where(DimLocal.is_current.is_(True))
        .distinct(DimLocal.sigla_uf)
        .order_by(DimLocal.sigla_uf, DimLocal.id)
    )
    return await paginate(
        db,
        query,
        params,
        transformer=lambda rows: [UFResponse.model_validate(r._mapping) for r in rows],
    )


@router.get("/ufs/{uf}/municipios", response_model=list[MunicipioResponse])
async def listar_municipios(
    uf: str,
    db: AsyncSession | None = Depends(get_db),
) -> list[MunicipioResponse]:
    if settings.sample_mode:
        raise HTTPException(status_code=503, detail="Not available in sample mode")
    assert db is not None  # get_db only yields None in SAMPLE_MODE, guarded above

    # uf path param is user-controlled; only used in parameterized .where() — no SQL concatenation.
    # tem_dados: True when the municipality has at least one row in mv_taxa_municipio_ano,
    # so the frontend can show all municipalities and grey-out those without data.
    has_data = (
        select(literal(1))
        .where(_mv_taxa.c.codigo_ibge_6 == DimLocal.codigo_ibge_6)
        .correlate(DimLocal)
        .exists()
        .label("tem_dados")
    )
    query = (
        select(
            DimLocal.codigo_ibge_6.label("codigo_ibge"),
            DimLocal.nome_municipio.label("nome"),
            DimLocal.sigla_uf,
            DimLocal.codigo_ibge_7.label("codigo_topojson"),
            has_data,
        )
        .where(DimLocal.sigla_uf == uf.upper())
        .where(DimLocal.is_current.is_(True))
        .order_by(DimLocal.nome_municipio)
    )
    result = await db.execute(query)
    rows = result.mappings().all()
    return [MunicipioResponse.model_validate(dict(r)) for r in rows]
