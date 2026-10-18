from sqlalchemy import (
    BIGINT,
    CHAR,
    Boolean,
    Column,
    Date,
    ForeignKey,
    Identity,
    Index,
    Integer,
    Numeric,
    SmallInteger,
    String,
    UniqueConstraint,
    text,
)

from app.models.base import Base


class FatoObitos(Base):
    """SIM (Sistema de Informações sobre Mortalidade) fact table.

    SIM revision support: upsert key = (numero_do, revisao_numero).
    """

    __tablename__ = "fato_obitos"
    __table_args__ = (
        UniqueConstraint(
            "numero_do", "revisao_numero", name="uq_fato_obitos_numerodo_revisao"
        ),
        Index(
            "ix_fato_obitos_tempo_local_causa",
            "dim_tempo_id",
            "dim_local_id",
            "dim_causa_id",
        ),
        Index("ix_fato_obitos_local", "dim_local_id"),
        Index("ix_fato_obitos_causa", "dim_causa_id"),
    )

    id = Column(BIGINT, Identity(always=True), primary_key=True)
    dim_tempo_id = Column(Integer, ForeignKey("dim_tempo.id"), nullable=False)
    dim_local_id = Column(Integer, ForeignKey("dim_local.id"), nullable=False)
    dim_causa_id = Column(Integer, ForeignKey("dim_causa.id"), nullable=False)
    dim_faixa_etaria_id = Column(
        Integer, ForeignKey("dim_faixa_etaria.id"), nullable=False
    )
    revisao_numero = Column(
        SmallInteger, nullable=False, default=0, server_default=text("0")
    )
    numero_do = Column(String(20), nullable=False)
    obitos = Column(Integer, nullable=False, default=1, server_default=text("1"))
    taxa_por_100k = Column(Numeric(10, 4), nullable=True)
    sexo = Column(CHAR(1), nullable=True)
    idade_anos = Column(SmallInteger, nullable=True)
    raca_cor = Column(CHAR(1), nullable=True)


class FatoInternacoes(Base):
    """SIH (Sistema de Informações Hospitalares) fact table.

    SIH AIH overcounting prevention: only incident AIHs loaded, filtered in
    staging on the raw DataSUS IDENT=1 field (not SP_TIPO — see
    etl/staging/sih_staging.py). sp_tipo here is a mart invariant flag,
    always 1. Filter enforced in ETL, not DB constraint.
    """

    __tablename__ = "fato_internacoes"
    __table_args__ = (
        UniqueConstraint("aih_numero", name="uq_fato_internacoes_aih"),
        Index(
            "ix_fato_internacoes_tempo_local_causa",
            "dim_tempo_id",
            "dim_local_id",
            "dim_causa_id",
        ),
        Index("ix_fato_internacoes_local", "dim_local_id"),
    )

    id = Column(BIGINT, Identity(always=True), primary_key=True)
    dim_tempo_id = Column(Integer, ForeignKey("dim_tempo.id"), nullable=False)
    dim_local_id = Column(Integer, ForeignKey("dim_local.id"), nullable=False)
    dim_causa_id = Column(Integer, ForeignKey("dim_causa.id"), nullable=False)
    dim_faixa_etaria_id = Column(
        Integer, ForeignKey("dim_faixa_etaria.id"), nullable=False
    )
    aih_numero = Column(String(20), nullable=False)
    sp_tipo = Column(SmallInteger, nullable=False, default=1, server_default=text("1"))
    internacoes = Column(Integer, nullable=False, default=1, server_default=text("1"))
    obitos_internacao = Column(
        Integer, nullable=False, default=0, server_default=text("0")
    )
    dias_permanencia = Column(Integer, nullable=True)
    taxa_por_100k = Column(Numeric(10, 4), nullable=True)
    valor_total = Column(Numeric(12, 2), nullable=True)


class FatoNotificacoes(Base):
    """SINAN (Sistema de Informação de Agravos de Notificação) fact table.

    The SINAN loader writes via raw psycopg2 execute_values, since the ETL
    runner never needed the ORM. The /notificacoes read API is the consumer
    that needs SQLAlchemy/fastapi_pagination access, so the model mirrors
    migration 0018 (+ 0020's dt_notific column) column for column.
    """

    __tablename__ = "fato_notificacoes"
    __table_args__ = (
        UniqueConstraint(
            "numero_notificacao",
            "tipo_agravo",
            name="uq_fato_notificacoes_numero_agravo",
        ),
        Index(
            "ix_fato_notificacoes_tempo_local_agravo",
            "dim_tempo_id",
            "dim_local_id",
            "dim_agravo_id",
        ),
        Index("ix_fato_notificacoes_local", "dim_local_id"),
        Index("ix_fato_notificacoes_dt_notific", "dim_agravo_id", "dt_notific"),
    )

    id = Column(BIGINT, Identity(always=True), primary_key=True)
    dim_tempo_id = Column(Integer, ForeignKey("dim_tempo.id"), nullable=False)
    dim_local_id = Column(Integer, ForeignKey("dim_local.id"), nullable=False)
    dim_agravo_id = Column(Integer, ForeignKey("dim_agravo.id"), nullable=False)
    dim_faixa_etaria_id = Column(
        Integer, ForeignKey("dim_faixa_etaria.id"), nullable=False
    )
    tipo_agravo = Column(String(10), nullable=False)
    numero_notificacao = Column(String(40), nullable=False)
    notificacoes = Column(Integer, nullable=False, default=1, server_default=text("1"))
    taxa_por_100k = Column(Numeric(10, 4), nullable=True)
    sexo = Column(CHAR(1), nullable=True)
    idade_anos = Column(SmallInteger, nullable=True)
    classi_fin = Column(SmallInteger, nullable=True)
    gravidade_grave = Column(Boolean, nullable=True)
    tra_classi = Column(SmallInteger, nullable=True)
    tp_acidente = Column(SmallInteger, nullable=True)
    dt_notific = Column(Date, nullable=True)
