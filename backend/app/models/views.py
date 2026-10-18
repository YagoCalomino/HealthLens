"""Read-only handles onto unmanaged Postgres materialized views.

These views are NOT part of app.models.base.metadata (Alembic's autogenerate
target, see alembic/env.py) — they already exist in the database, created and
refreshed outside the migration chain. Binding them to Base.metadata would
make `alembic revision --autogenerate` see them as "missing" ORM-declared
tables and try to CREATE TABLE them, which would either fail (object already
exists) or shadow the real materialized view. Each view therefore gets its
own throwaway MetaData() and is defined as a plain sqlalchemy.Table, queried
via Core select() only — never through the ORM session's identity map.
"""

from sqlalchemy import (
    BigInteger,
    Boolean,
    Column,
    Date,
    Integer,
    MetaData,
    Numeric,
    String,
    Table,
)

_views_metadata = MetaData()

mv_curva_epidemica = Table(
    "mv_curva_epidemica",
    _views_metadata,
    Column("dt_notific", Date),
    Column("dim_local_id", Integer),
    Column("agravo", String),
    Column("sigla_uf", String(2)),
    Column("total_notificacoes", BigInteger),
    Column("populacao", Numeric),
)


mv_curva_epidemica_semana = Table(
    "mv_curva_epidemica_semana",
    _views_metadata,
    Column("agravo", String),
    Column("sigla_uf", String(2)),
    Column("ano_epidemiologico", Integer),
    Column("semana_epidemiologica", Integer),
    Column("total_notificacoes", BigInteger),
    Column("total_populacao", Numeric),
)

mv_curva_epidemica_municipio_semana = Table(
    "mv_curva_epidemica_municipio_semana",
    _views_metadata,
    Column("agravo", String),
    Column("sigla_uf", String(2)),
    Column("dim_local_id", Integer),
    Column("ano_epidemiologico", Integer),
    Column("semana_epidemiologica", Integer),
    Column("total_notificacoes", BigInteger),
    Column("total_populacao", Numeric),
)

mv_breakdown_anual = Table(
    "mv_breakdown_anual",
    _views_metadata,
    Column("agravo", String),
    Column("sigla_uf", String(2)),
    Column("ano", Integer),
    Column("sexo", String(1)),
    Column("classi_fin", Integer),
    Column("gravidade_grave", Boolean),
    Column("tra_classi", Integer),
    Column("tp_acidente", Integer),
    Column("faixa_etaria_codigo", String),
    Column("faixa_etaria_descricao", String),
    Column("faixa_etaria_ordem", Integer),
    Column("total_notificacoes", BigInteger),
)

mv_uf_summary_anual = Table(
    "mv_uf_summary_anual",
    _views_metadata,
    Column("agravo", String),
    Column("sigla_uf", String(2)),
    Column("ano", Integer),
    Column("total_notificacoes", BigInteger),
    Column("total_populacao", BigInteger),
)
