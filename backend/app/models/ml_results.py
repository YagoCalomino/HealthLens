from sqlalchemy import (
    BIGINT,
    Column,
    ForeignKey,
    Identity,
    Index,
    Integer,
    JSON,
    Numeric,
    SmallInteger,
    String,
    Text,
    TIMESTAMP,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB

from app.models.base import Base


class ForecastResultados(Base):
    """ML pre-compute architecture: tables populated offline by ML runner. API is read-only.

    Uniqueness is enforced at the DB level by the NULLS NOT DISTINCT unique index
    uq_forecast_resultados (migration 0014), NOT by an ORM UniqueConstraint.
    Do NOT add a UniqueConstraint here — migration 0014 specifically replaced the
    ORM constraint with a DB-level NULLS NOT DISTINCT index so that ON CONFLICT
    correctly deduplicates all-cause rows where dim_causa_id IS NULL.
    """

    __tablename__ = "forecast_resultados"
    __table_args__ = (
        Index(
            "uq_forecast_resultados",
            "dim_local_id",
            "dim_causa_id",
            "metrica",
            "ano_referencia",
            "ano_forecast",
            "modelo_utilizado",
            unique=True,
            postgresql_nulls_not_distinct=True,
        ),
    )

    id = Column(BIGINT, Identity(always=True), primary_key=True)
    dim_local_id = Column(Integer, ForeignKey("dim_local.id"), nullable=False)
    dim_causa_id = Column(Integer, ForeignKey("dim_causa.id"), nullable=True)
    granularidade = Column(String(20), nullable=False)
    metrica = Column(String(30), nullable=False)
    ano_referencia = Column(SmallInteger, nullable=False)
    ano_forecast = Column(SmallInteger, nullable=False)
    valor_previsto = Column(Numeric(12, 4), nullable=False)
    intervalo_inferior_80 = Column(Numeric(12, 4), nullable=True)
    intervalo_superior_80 = Column(Numeric(12, 4), nullable=True)
    intervalo_inferior_95 = Column(Numeric(12, 4), nullable=True)
    intervalo_superior_95 = Column(Numeric(12, 4), nullable=True)
    mase = Column(Numeric(8, 4), nullable=True)
    smape = Column(Numeric(8, 4), nullable=True)
    modelo_utilizado = Column(String(50), nullable=False)
    criado_em = Column(TIMESTAMP, nullable=False, server_default=func.now())


class MunicipioClusterAssignments(Base):
    """ML pre-compute architecture: tables populated offline by ML runner. API is read-only."""

    __tablename__ = "municipio_cluster_assignments"
    __table_args__ = (
        UniqueConstraint(
            "dim_local_id",
            "algoritmo",
            "n_clusters",
            "ano_referencia",
            name="uq_municipio_cluster",
        ),
    )

    id = Column(Integer, Identity(always=True), primary_key=True)
    dim_local_id = Column(Integer, ForeignKey("dim_local.id"), nullable=False)
    cluster_id = Column(SmallInteger, nullable=False)
    algoritmo = Column(String(30), nullable=False)
    n_clusters = Column(SmallInteger, nullable=False)
    silhouette_score = Column(Numeric(6, 4), nullable=True)
    features_utilizadas = Column(Text, nullable=True)
    ano_referencia = Column(SmallInteger, nullable=False)
    cluster_nome = Column(String(100), nullable=True)
    pca_x = Column(Numeric(8, 4), nullable=True)
    pca_y = Column(Numeric(8, 4), nullable=True)
    # JSONB in PostgreSQL (migration 0013); plain JSON keeps the SQLite test harness working.
    features_norm = Column(JSON().with_variant(JSONB(), "postgresql"), nullable=True)
    criado_em = Column(TIMESTAMP, nullable=False, server_default=func.now())


class UfClusterAssignments(Base):
    """ML pre-compute architecture: tables populated offline by ML runner. API is read-only.

    Genuinely UF-grain clustering (KMeans + PCA fit on 27 UF-level feature
    rows) — not an aggregate of MunicipioClusterAssignments. See migration
    0021's docstring: averaging municipio-level PCA scores per UF collapsed
    pca_y toward zero for every UF.
    """

    __tablename__ = "uf_cluster_assignments"
    __table_args__ = (
        UniqueConstraint(
            "sigla_uf",
            "algoritmo",
            "n_clusters",
            "ano_referencia",
            name="uq_uf_cluster",
        ),
    )

    id = Column(Integer, Identity(always=True), primary_key=True)
    sigla_uf = Column(String(2), nullable=False)
    cluster_id = Column(SmallInteger, nullable=False)
    algoritmo = Column(String(30), nullable=False)
    n_clusters = Column(SmallInteger, nullable=False)
    silhouette_score = Column(Numeric(6, 4), nullable=True)
    features_utilizadas = Column(Text, nullable=True)
    ano_referencia = Column(SmallInteger, nullable=False)
    cluster_nome = Column(String(100), nullable=True)
    pca_x = Column(Numeric(8, 4), nullable=True)
    pca_y = Column(Numeric(8, 4), nullable=True)
    n_municipios = Column(SmallInteger, nullable=False)
    features_norm = Column(JSON, nullable=True)
    criado_em = Column(TIMESTAMP, nullable=False, server_default=func.now())
