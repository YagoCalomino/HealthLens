from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class HistoricoItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    ano: int
    valor: float | None = None


class PrevisaoItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    ano: int
    valor_previsto: float
    ci80_inf: float | None = None
    ci80_sup: float | None = None
    ci95_inf: float | None = None
    ci95_sup: float | None = None


class ModeloDetalhe(BaseModel):
    mase: float | None = None
    smape: float | None = None
    previsoes: list[PrevisaoItem]


class MunicipioInfo(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    codigo_ibge_6: str
    nome_municipio: str
    sigla_uf: str


class ForecastResponse(BaseModel):
    municipio: MunicipioInfo
    metrica: str
    ano_referencia: int
    historico: list[HistoricoItem]
    modelos: dict[str, ModeloDetalhe]
