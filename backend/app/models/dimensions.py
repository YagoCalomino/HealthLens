from sqlalchemy import (
    CHAR,
    Boolean,
    Column,
    Date,
    Identity,
    Index,
    Integer,
    SmallInteger,
    String,
    UniqueConstraint,
    text,
)

from app.models.base import Base


class DimTempo(Base):
    __tablename__ = "dim_tempo"
    __table_args__ = (UniqueConstraint("ano", "mes", name="uq_dim_tempo_ano_mes"),)

    id = Column(Integer, Identity(always=True), primary_key=True)
    ano = Column(SmallInteger, nullable=False)
    mes = Column(SmallInteger, nullable=True)
    trimestre = Column(SmallInteger, nullable=True)
    semestre = Column(SmallInteger, nullable=True)


class DimLocal(Base):
    __tablename__ = "dim_local"
    __table_args__ = (
        UniqueConstraint(
            "codigo_ibge_6", "valid_from", name="uq_dim_local_ibge6_valid_from"
        ),
        Index("ix_dim_local_ibge6", "codigo_ibge_6"),
        Index("ix_dim_local_ibge7", "codigo_ibge_7"),
    )

    id = Column(Integer, Identity(always=True), primary_key=True)
    # Both IBGE codes mandatory: codigo_ibge_6 is the DataSUS FK, codigo_ibge_7 (with check digit) matches TopoJSON
    codigo_ibge_6 = Column(CHAR(6), nullable=False)
    codigo_ibge_7 = Column(CHAR(7), nullable=False)
    nome_municipio = Column(String(100), nullable=False)
    nome_uf = Column(String(50), nullable=False)
    sigla_uf = Column(CHAR(2), nullable=False)
    codigo_uf = Column(CHAR(2), nullable=False)
    regiao = Column(String(20), nullable=False)
    valid_from = Column(Date, nullable=False)
    is_current = Column(
        Boolean, nullable=False, default=True, server_default=text("true")
    )
    ativo = Column(Boolean, nullable=False, default=True, server_default=text("true"))
    codigo_sucessor = Column(CHAR(6), nullable=True)


class DimCausa(Base):
    __tablename__ = "dim_causa"
    __table_args__ = (
        Index("ix_dim_causa_capitulo", "capitulo"),
        Index("ix_dim_causa_categoria", "categoria"),
    )

    id = Column(Integer, Identity(always=True), primary_key=True)
    codigo_cid10 = Column(String(5), nullable=False, unique=True)
    descricao = Column(String(500), nullable=False)
    capitulo = Column(String(5), nullable=False)
    categoria = Column(String(5), nullable=False)
    subcategoria = Column(String(5), nullable=True)
    grupo_descricao = Column(String(200), nullable=True)


class DimFaixaEtaria(Base):
    __tablename__ = "dim_faixa_etaria"

    id = Column(Integer, Identity(always=True), primary_key=True)
    codigo = Column(String(10), nullable=False, unique=True)
    descricao = Column(String(50), nullable=False)
    idade_min = Column(SmallInteger, nullable=False)
    idade_max = Column(SmallInteger, nullable=True)
    ordem = Column(SmallInteger, nullable=False)


class DimAgravo(Base):
    """SINAN agravo lookup (DENG/CHIK/ANIM). Row set is closed and seeded
    inline by migration 0017 — no seed script, unlike dim_faixa_etaria/
    CID-10/IBGE/TCU's larger external catalogs.
    """

    __tablename__ = "dim_agravo"

    id = Column(Integer, Identity(always=True), primary_key=True)
    codigo = Column(String(10), nullable=False, unique=True)
    descricao = Column(String(50), nullable=False)


class DimPopulacao(Base):
    __tablename__ = "dim_populacao"
    __table_args__ = (
        UniqueConstraint("codigo_ibge_6", "ano", name="uq_dim_populacao_ibge6_ano"),
    )

    id = Column(Integer, Identity(always=True), primary_key=True)
    codigo_ibge_6 = Column(CHAR(6), nullable=False)
    ano = Column(SmallInteger, nullable=False)
    populacao_total = Column(Integer, nullable=False)
    fonte = Column(
        String(50), nullable=False, default="TCU", server_default=text("'TCU'")
    )
