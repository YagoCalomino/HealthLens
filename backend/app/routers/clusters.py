from __future__ import annotations

import json

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi_pagination.cursor import CursorPage, CursorParams
from fastapi_pagination.ext.sqlalchemy import paginate
from sqlalchemy import Text, cast, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db import get_db
from app.models.dimensions import DimLocal
from app.models.ml_results import MunicipioClusterAssignments as MCA
from app.models.ml_results import UfClusterAssignments as UCA
from app.schemas.clusters import ClusterItemResponse, ClusterUfSummaryResponse

router = APIRouter(prefix="/clusters", tags=["clusters"])


async def _resolve_ano_e_n_clusters(
    db: AsyncSession,
    model,
    *,
    algoritmo: str,
    ano_referencia: int | None,
    n_clusters: int | None,
) -> tuple[int, int]:
    """Shared run-selection logic for /clusters and /clusters/uf-summary —
    parameterized by model so each endpoint resolves against its own table
    (MunicipioClusterAssignments vs UfClusterAssignments are independent ML
    runs, not guaranteed to share ano_referencia/n_clusters values)."""
    if ano_referencia is None:
        max_ano_ref = await db.scalar(
            select(func.max(model.ano_referencia)).where(model.algoritmo == algoritmo)
        )
        if max_ano_ref is None:
            raise HTTPException(
                status_code=503, detail="Sem dados de clusters disponíveis"
            )
        ano_ref = max_ano_ref
    else:
        ano_ref = ano_referencia

    if n_clusters is None:
        n_clusters_val = await db.scalar(
            select(func.max(model.n_clusters)).where(
                model.algoritmo == algoritmo,
                model.ano_referencia == ano_ref,
            )
        )
        if n_clusters_val is None:
            raise HTTPException(
                status_code=503, detail="Sem dados de clusters disponíveis"
            )
    else:
        n_clusters_val = n_clusters

    return ano_ref, n_clusters_val


@router.get("/", response_model=CursorPage[ClusterItemResponse])
async def listar_clusters(
    db: AsyncSession | None = Depends(get_db),
    params: CursorParams = Depends(),
    uf: str | None = Query(default=None, max_length=2),
    algoritmo: str = Query(default="KMeans", max_length=30),
    n_clusters: int | None = Query(default=None, ge=2, le=100),
    ano_referencia: int | None = Query(default=None, ge=1990, le=2100),
) -> CursorPage[ClusterItemResponse]:
    if settings.sample_mode:
        raise HTTPException(status_code=503, detail="Not available in sample mode")
    if db is None:
        raise HTTPException(status_code=503, detail="Not available in sample mode")

    ano_ref, n_clusters_val = await _resolve_ano_e_n_clusters(
        db,
        MCA,
        algoritmo=algoritmo,
        ano_referencia=ano_referencia,
        n_clusters=n_clusters,
    )

    # Inner subquery wraps window functions to isolate them from fastapi-pagination's COUNT wrapper.
    # Without .subquery(), the COUNT subquery sees AVG() OVER inside an aggregate context,
    # causing ProgrammingError on window functions in aggregate context.
    inner = (
        select(
            MCA.dim_local_id,
            MCA.cluster_id,
            MCA.cluster_nome,
            MCA.pca_x,
            MCA.pca_y,
            cast(MCA.features_norm, Text).label("features_norm"),
            MCA.silhouette_score,
            MCA.ano_referencia,
            func.avg(MCA.pca_x)
            .over(partition_by=[MCA.cluster_id, MCA.ano_referencia])
            .label("centroid_pca_x"),
            func.avg(MCA.pca_y)
            .over(partition_by=[MCA.cluster_id, MCA.ano_referencia])
            .label("centroid_pca_y"),
        )
        .where(
            MCA.algoritmo == algoritmo,
            MCA.ano_referencia == ano_ref,
            MCA.n_clusters
            == n_clusters_val,  # isolate single n_clusters run to prevent centroid mixing
        )
        .subquery()
    )

    # Outer query joins dim_local for geography fields.
    # uf filter applied here (outer scope) — not in inner — so DimLocal is available.
    query = (
        select(
            DimLocal.codigo_ibge_6,
            DimLocal.codigo_ibge_7,
            DimLocal.nome_municipio,
            DimLocal.sigla_uf,
            inner.c.cluster_id,
            inner.c.cluster_nome,
            inner.c.pca_x,
            inner.c.pca_y,
            inner.c.centroid_pca_x,
            inner.c.centroid_pca_y,
            inner.c.features_norm,
            inner.c.silhouette_score,
            inner.c.ano_referencia,
        )
        .select_from(inner)
        .join(DimLocal, inner.c.dim_local_id == DimLocal.id)
        # SCD-2: exclude retired municipality rows
        .where(DimLocal.is_current == True)  # noqa: E712
        .order_by(DimLocal.sigla_uf, DimLocal.nome_municipio)
    )

    # uf.upper() normalizes input ("sp" → "SP") before parameterized WHERE.
    # SQLAlchemy parameterized — no string interpolation into SQL.
    if uf:
        query = query.where(DimLocal.sigla_uf == uf.upper())

    return await paginate(
        db,
        query,
        params,
        transformer=lambda rows: [
            ClusterItemResponse.model_validate(
                {
                    **r._mapping,
                    "features_norm": json.loads(r._mapping["features_norm"])
                    if r._mapping.get("features_norm") is not None
                    else None,
                }
            )
            for r in rows
        ],
    )


@router.get("/uf-summary", response_model=list[ClusterUfSummaryResponse])
async def listar_clusters_uf_summary(
    db: AsyncSession | None = Depends(get_db),
    algoritmo: str = Query(default="KMeans", max_length=30),
    n_clusters: int | None = Query(default=None, ge=2, le=100),
    ano_referencia: int | None = Query(default=None, ge=1990, le=2100),
) -> list[ClusterUfSummaryResponse]:
    """One row per UF — the national-view companion to `/clusters`' município
    grain. Mirrors the two-level choropleth pattern: national
    view shows 27 points, município detail is loaded lazily once a UF is
    selected.

    Backed by `uf_cluster_assignments`, a genuinely UF-grain KMeans+PCA run
    (`ml.run_clustering.run_clustering_uf`) — NOT an aggregate of
    MunicipioClusterAssignments. An earlier version of this endpoint averaged
    each UF's municípios' already-computed pca_x/pca_y; PCA scores are
    mean-centered at zero by construction, so averaging pca_y (a
    lower-variance component dominated by município-to-município noise
    rather than UF-level signal) collapsed toward zero for every UF,
    producing a flat horizontal line instead of a 2D scatter. A
    dedicated UF-grain clustering run decomposes UF-level variance directly
    instead of reusing components fit for município-level variance.
    """
    if settings.sample_mode:
        raise HTTPException(status_code=503, detail="Not available in sample mode")
    if db is None:
        raise HTTPException(status_code=503, detail="Not available in sample mode")

    ano_ref, n_clusters_val = await _resolve_ano_e_n_clusters(
        db,
        UCA,
        algoritmo=algoritmo,
        ano_referencia=ano_referencia,
        n_clusters=n_clusters,
    )

    query = (
        select(UCA)
        .where(
            UCA.algoritmo == algoritmo,
            UCA.ano_referencia == ano_ref,
            UCA.n_clusters == n_clusters_val,
        )
        .order_by(UCA.sigla_uf)
    )
    rows = (await db.execute(query)).scalars().all()
    return [ClusterUfSummaryResponse.model_validate(row) for row in rows]
