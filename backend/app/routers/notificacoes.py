"""GET /notificacoes routes — raw-record cursor page plus two
aggregate siblings, uf-summary and municipio-summary, so the client
never aggregates already-paginated raw rows itself. Also the epidemic-curve
and categorical breakdown aggregates.

Every route opens with the SAMPLE_MODE guard: there is no SINAN sample
Parquet fixture (`etl/pipeline.py` logs "no SINAN sample fixture" in sample
mode), so a missing guard would surface a raw DB-connection error instead of
a clean 503.
"""

from __future__ import annotations

import logging
from datetime import date
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi_pagination.cursor import CursorPage, CursorParams
from fastapi_pagination.ext.sqlalchemy import paginate
from sqlalchemy import ColumnElement, Select, func, literal, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.constants.sinan import decode_classi_fin, decode_tp_acidente, decode_tra_classi
from app.db import get_db
from app.lib.epiweek import epi_weeks_no_intervalo, semana_epidemiologica
from app.models.dimensions import DimAgravo, DimFaixaEtaria, DimLocal, DimTempo
from app.models.facts import FatoNotificacoes
from app.models.views import (
    mv_curva_epidemica_semana,
    mv_curva_epidemica_municipio_semana,
    mv_breakdown_anual,
    mv_uf_summary_anual,
)
from app.schemas.notificacoes import (
    BreakdownResponse,
    CurvaEpidemicaResponse,
    NotificacaoResponse,
    NotificacaoSummaryResponse,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/notificacoes", tags=["notificacoes"])

BreakdownCampo = Literal[
    "classi_fin", "gravidade", "tra_classi", "tp_acidente", "faixa_etaria", "sexo"
]

# Agravo/campo compatibility matrix: the underlying
# columns are physically disjoint per agravo (migration 0018's docstring) —
# classi_fin/gravidade only exist for DENG/CHIK, tra_classi/tp_acidente only
# for ANIM. faixa_etaria and sexo are deliberately absent from this dict —
# they are agravo-agnostic and valid for any agravo, including omitted.
_BREAKDOWN_AGRAVO_REQUIREMENTS: dict[str, tuple[str, ...]] = {
    "classi_fin": ("DENG", "CHIK"),
    "gravidade": ("DENG", "CHIK"),
    "tra_classi": ("ANIM",),
    "tp_acidente": ("ANIM",),
}

# Raw-column source per campo for the non-faixa_etaria breakdowns —
# module-level so the route body stays a single GROUP BY construction
# instead of dynamic getattr(Model, campo) column resolution.
# Typed as ColumnElement[Any] since the underlying columns have different
# scalar types (SmallInteger vs Boolean vs CHAR) — a single dict cannot
# preserve each column's concrete type.
_BREAKDOWN_COLUMNS: dict[str, ColumnElement[Any]] = {
    "classi_fin": FatoNotificacoes.classi_fin,
    "gravidade": FatoNotificacoes.gravidade_grave,
    "tra_classi": FatoNotificacoes.tra_classi,
    "tp_acidente": FatoNotificacoes.tp_acidente,
    "sexo": FatoNotificacoes.sexo,
}


def _decode_gravidade(value: bool | None) -> str:
    """Tri-state gravidade_grave decoder — True/False/NULL, never dropped."""
    if value is True:
        return "Grave"
    if value is False:
        return "Não grave"
    return "Ignorado"


def _decode_sexo(value: str | None) -> str:
    """M/F/NULL sexo decoder — NULL surfaces as Ignorado, never dropped."""
    if value == "M":
        return "Masculino"
    if value == "F":
        return "Feminino"
    return "Ignorado"


def _apply_filters(
    query: Select,
    *,
    agravo: str | None,
    uf: str | None,
    municipio: str | None,
    classi_fin: int | None,
    ano_inicio: int | None,
    ano_fim: int | None,
) -> Select:
    """Shared filter application for all three /notificacoes routes — kept in
    one place so raw-record and aggregate routes can never drift in filter
    semantics. Every filter is a parameterized `.where(...)`; never
    string interpolation.
    """
    if agravo:
        query = query.where(DimAgravo.codigo == agravo)
    if uf:
        query = query.where(DimLocal.sigla_uf == uf.upper())
    if municipio:
        query = query.where(DimLocal.codigo_ibge_6 == municipio)
    if classi_fin is not None:
        query = query.where(FatoNotificacoes.classi_fin == classi_fin)
    if ano_inicio:
        query = query.where(DimTempo.ano >= ano_inicio)
    if ano_fim:
        query = query.where(DimTempo.ano <= ano_fim)
    return query


def _municipio_level_subquery(
    *,
    agravo: str | None,
    uf: str | None,
    municipio: str | None,
    classi_fin: int | None,
    ano_inicio: int | None,
    ano_fim: int | None,
):
    """Aggregate fato_notificacoes to (dim_local_id, sigla_uf, agravo, ano) —
    one row per município — reconstructing that município's population from
    its own rows' taxa_por_100k (loaded as 1 / populacao * 100000 per
    notification, notificacoes_loader.py). Every row within one município's
    group shares the same population, so AVG is exact modulo the column's
    NUMERIC(10,4) rounding.

    A caller that further GROUPs this by sigla_uf (or nothing, for a
    national total) can then compute
    SUM(muni_notificacoes) * 100000 / SUM(muni_populacao) — the correct
    incidence rate. Summing the already-computed per-município rates
    instead (the previous approach) silently weighted every município
    equally regardless of its population, inflating any aggregate spanning
    more than one município by up to two orders of magnitude.
    """
    query = (
        select(
            DimLocal.id.label("dim_local_id"),
            DimLocal.sigla_uf,
            DimAgravo.codigo.label("agravo"),
            DimTempo.ano,
            func.sum(FatoNotificacoes.notificacoes).label("muni_notificacoes"),
            func.avg(100000.0 / func.nullif(FatoNotificacoes.taxa_por_100k, 0)).label(
                "muni_populacao"
            ),
        )
        .select_from(FatoNotificacoes)
        .join(DimAgravo, FatoNotificacoes.dim_agravo_id == DimAgravo.id)
        .join(DimLocal, FatoNotificacoes.dim_local_id == DimLocal.id)
        .join(DimTempo, FatoNotificacoes.dim_tempo_id == DimTempo.id)
    )
    query = _apply_filters(
        query,
        agravo=agravo,
        uf=uf,
        municipio=municipio,
        classi_fin=classi_fin,
        ano_inicio=ano_inicio,
        ano_fim=ano_fim,
    )
    return query.group_by(
        DimLocal.id, DimLocal.sigla_uf, DimAgravo.codigo, DimTempo.ano
    ).subquery()


def _row_to_notificacao_response(row) -> NotificacaoResponse:
    """Derive semana_epidemiologica/ano_epidemiologico and the *_label fields
    per row, after the DB round trip — these are never stored columns.
    A NULL dt_notific yields NULL for both epi-week fields (older rows
    loaded before migration 0020 may not have it).
    """
    m = row._mapping
    agravo = m["agravo"]
    dt_notific = m["dt_notific"]

    if dt_notific is not None:
        ano_epidemiologico, semana_epi = semana_epidemiologica(dt_notific)
    else:
        ano_epidemiologico = None
        semana_epi = None

    taxa = m["taxa_por_100k"]

    return NotificacaoResponse(
        id=m["id"],
        agravo=agravo,
        sigla_uf=m["sigla_uf"],
        codigo_ibge=m["codigo_ibge"],
        nome_municipio=m["nome_municipio"],
        ano=m["ano"],
        mes=m["mes"],
        dt_notific=dt_notific,
        semana_epidemiologica=semana_epi,
        ano_epidemiologico=ano_epidemiologico,
        sexo=m["sexo"],
        idade_anos=m["idade_anos"],
        faixa_etaria=m["faixa_etaria"],
        classi_fin=m["classi_fin"],
        classi_fin_label=decode_classi_fin(agravo, m["classi_fin"]),
        gravidade_grave=m["gravidade_grave"],
        tra_classi=m["tra_classi"],
        tra_classi_label=decode_tra_classi(m["tra_classi"]),
        tp_acidente=m["tp_acidente"],
        tp_acidente_label=decode_tp_acidente(m["tp_acidente"]),
        taxa_por_100k=float(taxa) if taxa is not None else None,
    )


@router.get("/", response_model=CursorPage[NotificacaoResponse])
async def listar_notificacoes(
    db: AsyncSession | None = Depends(get_db),
    params: CursorParams = Depends(),
    agravo: Literal["DENG", "CHIK", "ANIM"] | None = Query(default=None),
    uf: str | None = Query(default=None, max_length=2),
    municipio: str | None = Query(default=None, max_length=6),
    classi_fin: int | None = Query(default=None),
    ano_inicio: int | None = Query(default=None, ge=1990, le=2100),
    ano_fim: int | None = Query(default=None, ge=1990, le=2100),
):
    """Raw-record drill-down. numero_notificacao is deliberately not
    projected (surrogate key leakage)."""
    if settings.sample_mode:
        raise HTTPException(status_code=503, detail="Not available in sample mode")
    assert db is not None  # get_db only yields None in SAMPLE_MODE, guarded above

    query = (
        select(
            FatoNotificacoes.id,
            DimAgravo.codigo.label("agravo"),
            DimLocal.sigla_uf,
            DimLocal.codigo_ibge_7.label("codigo_ibge"),
            DimLocal.nome_municipio,
            DimTempo.ano,
            DimTempo.mes,
            FatoNotificacoes.dt_notific,
            FatoNotificacoes.sexo,
            FatoNotificacoes.idade_anos,
            DimFaixaEtaria.codigo.label("faixa_etaria"),
            FatoNotificacoes.classi_fin,
            FatoNotificacoes.gravidade_grave,
            FatoNotificacoes.tra_classi,
            FatoNotificacoes.tp_acidente,
            FatoNotificacoes.taxa_por_100k,
        )
        .select_from(FatoNotificacoes)
        .join(DimAgravo, FatoNotificacoes.dim_agravo_id == DimAgravo.id)
        .join(DimLocal, FatoNotificacoes.dim_local_id == DimLocal.id)
        .join(DimTempo, FatoNotificacoes.dim_tempo_id == DimTempo.id)
        .join(DimFaixaEtaria, FatoNotificacoes.dim_faixa_etaria_id == DimFaixaEtaria.id)
    )
    query = _apply_filters(
        query,
        agravo=agravo,
        uf=uf,
        municipio=municipio,
        classi_fin=classi_fin,
        ano_inicio=ano_inicio,
        ano_fim=ano_fim,
    )
    # sqlakeyset (fastapi_pagination's cursor backend) requires a unique row
    # ordering — id is the only unique column on fato_notificacoes.
    query = query.order_by(FatoNotificacoes.id)

    return await paginate(
        db,
        query,
        params,
        transformer=lambda rows: [_row_to_notificacao_response(r) for r in rows],
    )


@router.get("/uf-summary", response_model=list[NotificacaoSummaryResponse])
async def listar_notificacoes_uf_summary(
    db: AsyncSession | None = Depends(get_db),
    agravo: Literal["DENG", "CHIK", "ANIM"] | None = Query(default=None),
    uf: str | None = Query(default=None, max_length=2),
    municipio: str | None = Query(default=None, max_length=6),
    classi_fin: int | None = Query(default=None),
    ano_inicio: int | None = Query(default=None, ge=1990, le=2100),
    ano_fim: int | None = Query(default=None, ge=1990, le=2100),
) -> list[NotificacaoSummaryResponse]:
    """One aggregate row per (sigla_uf, agravo, ano) — no pagination;
    GROUP BY-bounded to ~810 rows max (27 UFs x 3 agravos x ~10 anos).
    """
    if settings.sample_mode:
        raise HTTPException(status_code=503, detail="Not available in sample mode")
    assert db is not None

    # Fast path: mv_uf_summary_anual is already one row per (agravo, uf, ano) with
    # population summed over contributing municípios, same as the slow path.
    # It has no municipio or classi_fin column, so either filter falls through.
    if not municipio and classi_fin is None:
        mv_s = mv_uf_summary_anual
        q = select(
            mv_s.c.sigla_uf,
            literal(None).label("codigo_ibge"),
            literal(None).label("nome_municipio"),
            mv_s.c.agravo,
            mv_s.c.ano,
            mv_s.c.total_notificacoes,
            (
                mv_s.c.total_notificacoes
                * 100_000.0
                / func.nullif(mv_s.c.total_populacao, 0)
            ).label("taxa_por_100k"),
        ).select_from(mv_s)
        if agravo:
            q = q.where(mv_s.c.agravo == agravo)
        if uf:
            q = q.where(mv_s.c.sigla_uf == uf.upper())
        if ano_inicio:
            q = q.where(mv_s.c.ano >= ano_inicio)
        if ano_fim:
            q = q.where(mv_s.c.ano <= ano_fim)
        q = q.order_by(mv_s.c.sigla_uf, mv_s.c.ano, mv_s.c.agravo)
        result = await db.execute(q)
        rows = result.mappings().all()
        return [NotificacaoSummaryResponse(**dict(r)) for r in rows]

    muni_level = _municipio_level_subquery(
        agravo=agravo,
        uf=uf,
        municipio=municipio,
        classi_fin=classi_fin,
        ano_inicio=ano_inicio,
        ano_fim=ano_fim,
    )
    total_notificacoes = func.sum(muni_level.c.muni_notificacoes)
    total_populacao = func.sum(muni_level.c.muni_populacao)
    query = (
        select(
            muni_level.c.sigla_uf,
            literal(None).label("codigo_ibge"),
            literal(None).label("nome_municipio"),
            muni_level.c.agravo,
            muni_level.c.ano,
            total_notificacoes.label("total_notificacoes"),
            # UF rate = total notificações / total população of the UF's
            # contributing municípios — never the sum of per-município rates:
            # those are weighted by 1/populacao each, so summing
            # them across municípios of differing size does not reconstruct
            # the UF's true incidence rate.
            (total_notificacoes * 100000.0 / func.nullif(total_populacao, 0)).label(
                "taxa_por_100k"
            ),
        )
        .select_from(muni_level)
        .group_by(muni_level.c.sigla_uf, muni_level.c.agravo, muni_level.c.ano)
        .order_by(muni_level.c.sigla_uf, muni_level.c.ano, muni_level.c.agravo)
    )

    result = await db.execute(query)
    rows = result.mappings().all()
    return [NotificacaoSummaryResponse(**dict(r)) for r in rows]


@router.get("/municipio-summary", response_model=list[NotificacaoSummaryResponse])
async def listar_notificacoes_municipio_summary(
    db: AsyncSession | None = Depends(get_db),
    agravo: Literal["DENG", "CHIK", "ANIM"] | None = Query(default=None),
    uf: str | None = Query(default=None, max_length=2),
    municipio: str | None = Query(default=None, max_length=6),
    classi_fin: int | None = Query(default=None),
    ano_inicio: int | None = Query(default=None, ge=1990, le=2100),
    ano_fim: int | None = Query(default=None, ge=1990, le=2100),
) -> list[NotificacaoSummaryResponse]:
    """Same aggregate shape as uf-summary, at município grain, for
    choropleth drill-down. Município grain is filterable by uf and covered
    by the existing dim_local/dim_agravo/dim_tempo indexes."""
    if settings.sample_mode:
        raise HTTPException(status_code=503, detail="Not available in sample mode")
    assert db is not None

    # Fast path: pre-aggregated MV at (agravo, uf, municipio, semana) grain (~544k rows).
    # classi_fin is not a column on this MV (aggregated across all classi_fin values).
    mv_m = mv_curva_epidemica_municipio_semana
    q = (
        select(
            DimLocal.sigla_uf,
            DimLocal.codigo_ibge_7.label("codigo_ibge"),
            DimLocal.nome_municipio,
            mv_m.c.agravo,
            mv_m.c.ano_epidemiologico.label("ano"),
            func.sum(mv_m.c.total_notificacoes).label("total_notificacoes"),
            (
                func.sum(mv_m.c.total_notificacoes)
                * 100_000.0
                / func.nullif(func.max(mv_m.c.total_populacao), 0)
            ).label("taxa_por_100k"),
        )
        .select_from(mv_m)
        .join(DimLocal, mv_m.c.dim_local_id == DimLocal.id)
    )
    if agravo:
        q = q.where(mv_m.c.agravo == agravo)
    if uf:
        q = q.where(mv_m.c.sigla_uf == uf.upper())
    if municipio:
        dim_local_subq = (
            select(DimLocal.id)
            .where(DimLocal.codigo_ibge_6 == municipio)
            .scalar_subquery()
        )
        q = q.where(mv_m.c.dim_local_id == dim_local_subq)
    if ano_inicio:
        q = q.where(mv_m.c.ano_epidemiologico >= ano_inicio)
    if ano_fim:
        q = q.where(mv_m.c.ano_epidemiologico <= ano_fim)
    q = q.group_by(
        DimLocal.sigla_uf,
        DimLocal.codigo_ibge_7,
        DimLocal.nome_municipio,
        mv_m.c.agravo,
        mv_m.c.ano_epidemiologico,
    ).order_by(
        DimLocal.sigla_uf,
        DimLocal.codigo_ibge_7,
        mv_m.c.ano_epidemiologico,
        mv_m.c.agravo,
    )

    result = await db.execute(q)
    rows = result.mappings().all()
    return [NotificacaoSummaryResponse(**dict(r)) for r in rows]


@router.get("/curva-epidemica", response_model=list[CurvaEpidemicaResponse])
async def curva_epidemica(
    db: AsyncSession | None = Depends(get_db),
    agravo: Literal["DENG", "CHIK", "ANIM"] | None = Query(default=None),
    uf: str | None = Query(default=None, max_length=2),
    municipio: str | None = Query(default=None, max_length=6),
    classi_fin: int | None = Query(default=None),
    ano_inicio: int | None = Query(default=None, ge=1990, le=2100),
    ano_fim: int | None = Query(default=None, ge=1990, le=2100),
) -> list[CurvaEpidemicaResponse]:
    """Epidemic curve by semana epidemiologica.

    Fast path (no municipio filter): queries mv_curva_epidemica_semana, a
    pre-aggregated MV at (agravo, sigla_uf, ano_epi, semana_epi) grain.
    Returns ~400 rows; ~5ms query time vs ~2000ms on the raw MV.

    Slow path (municipio filter): falls back to mv_curva_epidemica
    (day x municipality grain, ~1M rows for DENG) with Python-side
    epi-week bucketing. Kept for correctness; optimize separately.

    classi_fin is not a column on either view (aggregated across all
    classi_fin values), so a classi_fin filter is rejected.
    """
    if settings.sample_mode:
        raise HTTPException(status_code=503, detail="Not available in sample mode")
    assert db is not None

    if classi_fin is not None:
        raise HTTPException(
            status_code=422,
            detail="classi_fin is not filterable on /curva-epidemica -- mv_curva_epidemica "
            "aggregates across classi_fin values",
        )

    # -- SLOW PATH: municipio filter -- pre-aggregated MV by municipio+semana --
    if municipio:
        mv_m = mv_curva_epidemica_municipio_semana
        dim_local_subq = (
            select(DimLocal.id)
            .where(DimLocal.codigo_ibge_6 == municipio)
            .scalar_subquery()
        )
        q_m = (
            select(
                mv_m.c.ano_epidemiologico,
                mv_m.c.semana_epidemiologica,
                func.sum(mv_m.c.total_notificacoes).label("total_notificacoes"),
                func.sum(mv_m.c.total_populacao).label("total_populacao"),
            )
            .select_from(mv_m)
            .where(mv_m.c.dim_local_id == dim_local_subq)
        )
        if agravo:
            q_m = q_m.where(mv_m.c.agravo == agravo)
        if uf:
            q_m = q_m.where(mv_m.c.sigla_uf == uf.upper())
        if ano_inicio:
            q_m = q_m.where(mv_m.c.ano_epidemiologico >= ano_inicio)
        if ano_fim:
            q_m = q_m.where(mv_m.c.ano_epidemiologico <= ano_fim)
        q_m = q_m.group_by(mv_m.c.ano_epidemiologico, mv_m.c.semana_epidemiologica)

        result_m = await db.execute(q_m)
        week_rows_m = result_m.mappings().all()

        if not week_rows_m:
            return []

        buckets_m: dict[tuple[int, int], dict[str, Any]] = {}
        min_ano_m: int | None = None
        max_ano_m: int | None = None
        for row in week_rows_m:
            ano_epi = row["ano_epidemiologico"]
            semana_epi = row["semana_epidemiologica"]
            key = (ano_epi, semana_epi)
            total = int(row["total_notificacoes"])
            pop = row["total_populacao"]
            taxa = (
                float(total) * 100_000.0 / float(pop)
                if pop and float(pop) > 0
                else None
            )
            buckets_m[key] = {"total_notificacoes": total, "taxa_por_100k": taxa}
            if min_ano_m is None or ano_epi < min_ano_m:
                min_ano_m = ano_epi
            if max_ano_m is None or ano_epi > max_ano_m:
                max_ano_m = ano_epi

        if ano_inicio is not None and ano_fim is not None:
            range_inicio = date(ano_inicio, 1, 1)
            range_fim = date(ano_fim, 12, 31)
        else:
            range_inicio = date(min_ano_m, 1, 1)  # type: ignore[arg-type]
            range_fim = date(max_ano_m, 12, 31)  # type: ignore[arg-type]

        semanas_m = epi_weeks_no_intervalo(range_inicio, range_fim)
        response_m = [
            CurvaEpidemicaResponse(
                ano_epidemiologico=ano_epi,
                semana_epidemiologica=semana_epi,
                total_notificacoes=int(
                    buckets_m.get((ano_epi, semana_epi), {}).get(
                        "total_notificacoes", 0
                    )
                ),
                taxa_por_100k=buckets_m.get((ano_epi, semana_epi), {}).get(
                    "taxa_por_100k"
                )
                or None,
            )
            for ano_epi, semana_epi in semanas_m
        ]
        response_m.sort(key=lambda r: (r.ano_epidemiologico, r.semana_epidemiologica))
        return response_m

    # -- FAST PATH: pre-aggregated weekly MV (~5ms, ~400 rows) ----------------
    mv_s = mv_curva_epidemica_semana
    q = select(
        mv_s.c.ano_epidemiologico,
        mv_s.c.semana_epidemiologica,
        func.sum(mv_s.c.total_notificacoes).label("total_notificacoes"),
        func.sum(mv_s.c.total_populacao).label("total_populacao"),
    ).select_from(mv_s)
    if agravo:
        q = q.where(mv_s.c.agravo == agravo)
    if uf:
        q = q.where(mv_s.c.sigla_uf == uf.upper())
    if ano_inicio:
        q = q.where(mv_s.c.ano_epidemiologico >= ano_inicio)
    if ano_fim:
        q = q.where(mv_s.c.ano_epidemiologico <= ano_fim)
    q = q.group_by(mv_s.c.ano_epidemiologico, mv_s.c.semana_epidemiologica)

    result = await db.execute(q)
    week_rows = result.mappings().all()

    if not week_rows:
        return []

    buckets_w: dict[tuple[int, int], dict[str, Any]] = {}
    min_ano: int | None = None
    max_ano: int | None = None
    for row in week_rows:
        ano_epi = row["ano_epidemiologico"]
        semana_epi = row["semana_epidemiologica"]
        key = (ano_epi, semana_epi)
        total = int(row["total_notificacoes"])
        pop = row["total_populacao"]
        taxa = float(total) * 100_000.0 / float(pop) if pop and float(pop) > 0 else None
        buckets_w[key] = {"total_notificacoes": total, "taxa_por_100k": taxa}
        if min_ano is None or ano_epi < min_ano:
            min_ano = ano_epi
        if max_ano is None or ano_epi > max_ano:
            max_ano = ano_epi

    if ano_inicio is not None and ano_fim is not None:
        range_inicio = date(ano_inicio, 1, 1)
        range_fim = date(ano_fim, 12, 31)
    else:
        range_inicio = date(min_ano, 1, 1)  # type: ignore[arg-type]
        range_fim = date(max_ano, 12, 31)  # type: ignore[arg-type]

    semanas = epi_weeks_no_intervalo(range_inicio, range_fim)
    response = [
        CurvaEpidemicaResponse(
            ano_epidemiologico=ano_epi,
            semana_epidemiologica=semana_epi,
            total_notificacoes=int(
                buckets_w.get((ano_epi, semana_epi), {}).get("total_notificacoes", 0)
            ),
            taxa_por_100k=buckets_w.get((ano_epi, semana_epi), {}).get("taxa_por_100k")
            or None,
        )
        for ano_epi, semana_epi in semanas
    ]
    response.sort(key=lambda r: (r.ano_epidemiologico, r.semana_epidemiologica))
    return response


@router.get("/breakdown", response_model=list[BreakdownResponse])
async def breakdown(
    db: AsyncSession | None = Depends(get_db),
    campo: BreakdownCampo = Query(...),
    agravo: Literal["DENG", "CHIK", "ANIM"] | None = Query(default=None),
    uf: str | None = Query(default=None, max_length=2),
    municipio: str | None = Query(default=None, max_length=6),
    classi_fin: int | None = Query(default=None),
    ano_inicio: int | None = Query(default=None, ge=1990, le=2100),
    ano_fim: int | None = Query(default=None, ge=1990, le=2100),
) -> list[BreakdownResponse]:
    """Agravo-aware categorical breakdown — one shared surface
    whose category set changes per agravo, instead of exposing a fixed
    union of physically incompatible columns as separate charts.
    """
    if settings.sample_mode:
        raise HTTPException(status_code=503, detail="Not available in sample mode")
    assert db is not None

    required_agravos = _BREAKDOWN_AGRAVO_REQUIREMENTS.get(campo)
    if required_agravos is not None and (
        agravo is None or agravo not in required_agravos
    ):
        raise HTTPException(
            status_code=422,
            detail=(
                f"campo={campo!r} is only valid for agravo in {required_agravos!r} "
                "(the underlying column does not exist for other agravos); "
                "faixa_etaria and sexo are valid for any agravo"
            ),
        )

    # Fast path: mv_breakdown_anual (agravo x uf x ano x categorical columns) has
    # no municipio grain, so a município filter falls through to the fact table.
    if not municipio:
        mv_b = mv_breakdown_anual
        if campo == "faixa_etaria":
            group_cols = [
                mv_b.c.faixa_etaria_codigo,
                mv_b.c.faixa_etaria_descricao,
                mv_b.c.faixa_etaria_ordem,
            ]
            sel_cols = [
                mv_b.c.faixa_etaria_codigo.label("codigo"),
                mv_b.c.faixa_etaria_descricao.label("descricao"),
                mv_b.c.faixa_etaria_ordem.label("ordem"),
            ]
        else:
            mv_col = {
                "classi_fin": mv_b.c.classi_fin,
                "gravidade": mv_b.c.gravidade_grave,
                "tra_classi": mv_b.c.tra_classi,
                "tp_acidente": mv_b.c.tp_acidente,
                "sexo": mv_b.c.sexo,
            }[campo]
            group_cols = [mv_col]
            sel_cols = [mv_col.label("raw_codigo")]

        mv_total = func.sum(mv_b.c.total_notificacoes)
        q = select(*sel_cols, mv_total.label("total_notificacoes")).select_from(mv_b)
        if agravo:
            q = q.where(mv_b.c.agravo == agravo)
        if uf:
            q = q.where(mv_b.c.sigla_uf == uf.upper())
        if classi_fin is not None:
            q = q.where(mv_b.c.classi_fin == classi_fin)
        if ano_inicio:
            q = q.where(mv_b.c.ano >= ano_inicio)
        if ano_fim:
            q = q.where(mv_b.c.ano <= ano_fim)

        if campo == "faixa_etaria":
            q = q.group_by(*group_cols).order_by(mv_b.c.faixa_etaria_ordem)
            result = await db.execute(q)
            return [
                BreakdownResponse(
                    campo="faixa_etaria",
                    categoria=r["descricao"],
                    codigo=r["codigo"],
                    total_notificacoes=int(r["total_notificacoes"]),
                )
                for r in result.mappings().all()
            ]

        q = q.group_by(*group_cols).order_by(mv_total.desc())
        result = await db.execute(q)
        fast_resp: list[BreakdownResponse] = []
        for r in result.mappings().all():
            raw = r["raw_codigo"]
            cod: int | str | None
            if campo == "classi_fin":
                assert agravo is not None
                cat = decode_classi_fin(agravo, raw) if raw is not None else "Ignorado"
                cod = int(raw) if raw is not None else None
            elif campo == "gravidade":
                cat = _decode_gravidade(raw)
                cod = None
            elif campo == "tra_classi":
                cat = decode_tra_classi(raw) if raw is not None else "Ignorado"
                cod = int(raw) if raw is not None else None
            elif campo == "tp_acidente":
                cat = decode_tp_acidente(raw) if raw is not None else "Ignorado"
                cod = int(raw) if raw is not None else None
            else:
                cat = _decode_sexo(raw)
                cod = raw
            fast_resp.append(
                BreakdownResponse(
                    campo=campo,
                    categoria=cat,
                    codigo=cod,
                    total_notificacoes=int(r["total_notificacoes"]),
                )
            )
        return fast_resp

    total_col = func.sum(FatoNotificacoes.notificacoes).label("total_notificacoes")

    if campo == "faixa_etaria":
        query = (
            select(
                DimFaixaEtaria.codigo,
                DimFaixaEtaria.descricao,
                DimFaixaEtaria.ordem,
                total_col,
            )
            .select_from(FatoNotificacoes)
            .join(DimAgravo, FatoNotificacoes.dim_agravo_id == DimAgravo.id)
            .join(DimLocal, FatoNotificacoes.dim_local_id == DimLocal.id)
            .join(DimTempo, FatoNotificacoes.dim_tempo_id == DimTempo.id)
            .join(
                DimFaixaEtaria,
                FatoNotificacoes.dim_faixa_etaria_id == DimFaixaEtaria.id,
            )
        )
        query = _apply_filters(
            query,
            agravo=agravo,
            uf=uf,
            municipio=municipio,
            classi_fin=classi_fin,
            ano_inicio=ano_inicio,
            ano_fim=ano_fim,
        )
        query = query.group_by(
            DimFaixaEtaria.codigo, DimFaixaEtaria.descricao, DimFaixaEtaria.ordem
        )
        query = query.order_by(DimFaixaEtaria.ordem)

        result = await db.execute(query)
        rows = result.mappings().all()
        return [
            BreakdownResponse(
                campo="faixa_etaria",
                categoria=r["descricao"],
                codigo=r["codigo"],
                total_notificacoes=int(r["total_notificacoes"]),
            )
            for r in rows
        ]

    group_col = _BREAKDOWN_COLUMNS[campo]

    query = (
        select(group_col.label("raw_codigo"), total_col)
        .select_from(FatoNotificacoes)
        .join(DimAgravo, FatoNotificacoes.dim_agravo_id == DimAgravo.id)
        .join(DimLocal, FatoNotificacoes.dim_local_id == DimLocal.id)
        .join(DimTempo, FatoNotificacoes.dim_tempo_id == DimTempo.id)
    )
    query = _apply_filters(
        query,
        agravo=agravo,
        uf=uf,
        municipio=municipio,
        classi_fin=classi_fin,
        ano_inicio=ano_inicio,
        ano_fim=ano_fim,
    )
    query = query.group_by(group_col).order_by(total_col.desc())

    result = await db.execute(query)
    rows = result.mappings().all()

    response: list[BreakdownResponse] = []
    for r in rows:
        raw = r["raw_codigo"]
        total = int(r["total_notificacoes"])

        if campo == "classi_fin":
            # agravo is guaranteed non-None here — the compatibility-matrix
            # check above already rejected campo=classi_fin with agravo=None.
            assert agravo is not None
            categoria = (
                decode_classi_fin(agravo, raw) if raw is not None else "Ignorado"
            )
            codigo: int | str | None = int(raw) if raw is not None else None
        elif campo == "gravidade":
            categoria = _decode_gravidade(raw)
            codigo = None
        elif campo == "tra_classi":
            categoria = decode_tra_classi(raw) if raw is not None else "Ignorado"
            codigo = int(raw) if raw is not None else None
        elif campo == "tp_acidente":
            categoria = decode_tp_acidente(raw) if raw is not None else "Ignorado"
            codigo = int(raw) if raw is not None else None
        else:  # sexo
            categoria = _decode_sexo(raw)
            codigo = raw

        response.append(
            BreakdownResponse(
                campo=campo,
                categoria=categoria,
                codigo=codigo,
                total_notificacoes=total,
            )
        )

    return response
