from __future__ import annotations

import numpy as np
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import Column, MetaData, Numeric, SmallInteger, String, Table, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db import get_db
from app.models.dimensions import DimLocal
from app.models.ml_results import MunicipioClusterAssignments as MCA
from app.schemas.risco_prospectivo import (
    DistribuicaoPeers,
    MunicipioInfo,
    RiscoProspectivoResponse,
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

_ALGORITMO = "KMeans"
_N_CLUSTERS = 6
_FONTE = "SIM"
_HORIZONTE_ANOS = 3
_MIN_PEERS = 10
_TIPO_ANALISE = "comparacao_prospectiva"

router = APIRouter(prefix="/risco-prospectivo", tags=["risco-prospectivo"])


@router.get("/", response_model=RiscoProspectivoResponse)
async def obter_risco_prospectivo(
    db: AsyncSession | None = Depends(get_db),
    municipio: str = Query(..., max_length=6),
    ano_referencia: int = Query(..., ge=1990, le=2100),
) -> RiscoProspectivoResponse:
    """Retrospective comparative-risk distribution for a município and reference year T.

    This is a descriptive comparison, not a forecast: both T (`ano_referencia`) and
    T+3 (`ano_comparacao`) are already-elapsed years with real, observed
    `mv_taxa_municipio_ano` rates. The endpoint reports how the target município's
    cluster peers actually fared between T and T+3.

    Variation is fractional percentage change: `(taxa_T3 - taxa_T) / taxa_T`. The
    target município is excluded from its own peer distribution; its own
    percentage change is reported separately as `variacao_municipio`.

    Peers whose `taxa_T` is NULL or `0` are excluded from the percentage-change
    array before `n` is computed, since the formula is undefined there. `n`
    therefore reflects the post-exclusion peer count, and that same
    post-exclusion `n` feeds the `n >= _MIN_PEERS` sample-size guard. Below the
    guard the endpoint flags rather than suppresses: HTTP 200 with
    `amostra_insuficiente=True` and the (possibly small) distribution still
    populated.
    """
    if settings.sample_mode:
        raise HTTPException(status_code=503, detail="Not available in sample mode")
    if db is None:
        raise HTTPException(status_code=503, detail="Not available in sample mode")

    result_target = await db.execute(
        select(
            DimLocal.id,
            DimLocal.codigo_ibge_6,
            DimLocal.nome_municipio,
            DimLocal.sigla_uf,
        )
        .where(DimLocal.codigo_ibge_6 == municipio)
        .where(DimLocal.is_current == True)  # noqa: E712
        .limit(1)
    )
    target_row = result_target.one_or_none()
    if target_row is None:
        raise HTTPException(status_code=404, detail="Município não encontrado")

    target_id = target_row.id

    result_cluster = await db.execute(
        select(MCA.cluster_id, MCA.cluster_nome)
        .where(
            MCA.algoritmo == _ALGORITMO,
            MCA.n_clusters == _N_CLUSTERS,
            MCA.ano_referencia == ano_referencia,
            MCA.dim_local_id == target_id,
        )
        .limit(1)
    )
    cluster_row = result_cluster.one_or_none()
    if cluster_row is None:
        raise HTTPException(
            status_code=404,
            detail="Sem atribuição de cluster para o município no ano de referência",
        )

    target_cluster_id = cluster_row.cluster_id
    target_cluster_nome = cluster_row.cluster_nome

    result_peers = await db.execute(
        select(MCA.dim_local_id).where(
            MCA.algoritmo == _ALGORITMO,
            MCA.n_clusters == _N_CLUSTERS,
            MCA.ano_referencia == ano_referencia,
            MCA.cluster_id == target_cluster_id,
            MCA.dim_local_id != target_id,
        )
    )
    peer_ids = [r.dim_local_id for r in result_peers.fetchall()]

    result_peer_codigos = await db.execute(
        select(DimLocal.id, DimLocal.codigo_ibge_6)
        .where(DimLocal.id.in_(peer_ids))
        .where(DimLocal.is_current == True)  # noqa: E712
    )
    peer_codigos = [r.codigo_ibge_6 for r in result_peer_codigos.fetchall()]

    ano_comparacao = ano_referencia + _HORIZONTE_ANOS
    mv = mv_taxa_municipio_ano
    result_rates = await db.execute(
        select(mv.c.codigo_ibge_6, mv.c.ano, mv.c.taxa_por_100k)
        .where(mv.c.codigo_ibge_6.in_(peer_codigos + [municipio]))
        .where(mv.c.fonte == _FONTE)
        .where(mv.c.ano.in_([ano_referencia, ano_comparacao]))
    )
    rate_lookup: dict[tuple[str, int], float | None] = {}
    for r in result_rates.fetchall():
        rate_lookup[(r.codigo_ibge_6, r.ano)] = (
            float(r.taxa_por_100k) if r.taxa_por_100k is not None else None
        )

    has_comparacao_data = any(
        ano == ano_comparacao and taxa is not None
        for (_, ano), taxa in rate_lookup.items()
    )
    if not has_comparacao_data:
        raise HTTPException(
            status_code=404,
            detail=f"Sem dados reais de taxa para o ano de comparação {ano_comparacao}",
        )

    variacoes_peers: list[float] = []
    for codigo in peer_codigos:
        taxa_t = rate_lookup.get((codigo, ano_referencia))
        taxa_t3 = rate_lookup.get((codigo, ano_comparacao))
        if taxa_t is None or taxa_t3 is None or taxa_t == 0:
            continue
        variacoes_peers.append((taxa_t3 - taxa_t) / taxa_t)

    mediana: float | None
    p25: float | None
    p75: float | None
    minimo: float | None
    maximo: float | None
    if variacoes_peers:
        arr = np.array(variacoes_peers)
        n = len(arr)
        mediana = float(np.median(arr))
        p25, p75 = (float(v) for v in np.percentile(arr, [25, 75]))
        minimo = float(arr.min())
        maximo = float(arr.max())
    else:
        n = 0
        mediana = p25 = p75 = minimo = maximo = None

    amostra_insuficiente = n < _MIN_PEERS

    taxa_t_municipio = rate_lookup.get((municipio, ano_referencia))
    taxa_t3_municipio = rate_lookup.get((municipio, ano_comparacao))
    if taxa_t_municipio is None or taxa_t3_municipio is None or taxa_t_municipio == 0:
        variacao_municipio = None
    else:
        variacao_municipio = (taxa_t3_municipio - taxa_t_municipio) / taxa_t_municipio

    return RiscoProspectivoResponse(
        municipio=MunicipioInfo(
            codigo_ibge_6=municipio,
            nome_municipio=target_row.nome_municipio,
            sigla_uf=target_row.sigla_uf,
        ),
        ano_referencia=ano_referencia,
        ano_comparacao=ano_comparacao,
        cluster_id=target_cluster_id,
        cluster_nome=target_cluster_nome,
        variacao_municipio=variacao_municipio,
        distribuicao_peers=DistribuicaoPeers(
            n=n,
            mediana=mediana,
            p25=p25,
            p75=p75,
            minimo=minimo,
            maximo=maximo,
            amostra_insuficiente=amostra_insuficiente,
        ),
        tipo_analise=_TIPO_ANALISE,
    )
