from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class ClusterItemResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    codigo_ibge_6: str
    codigo_ibge_7: str
    nome_municipio: str
    sigla_uf: str
    cluster_id: int
    cluster_nome: str | None = None
    pca_x: float | None = None
    pca_y: float | None = None
    centroid_pca_x: float | None = None
    centroid_pca_y: float | None = None
    features_norm: dict[str, float] | None = None
    silhouette_score: float | None = None
    ano_referencia: int


class ClusterUfSummaryResponse(BaseModel):
    """National-view aggregate — one row per UF (two-level cluster view,
    mirrors the choropleth's national/municipal split)."""

    model_config = ConfigDict(from_attributes=True)

    sigla_uf: str
    cluster_id: int
    cluster_nome: str | None = None
    pca_x: float | None = None
    pca_y: float | None = None
    n_municipios: int
    ano_referencia: int
