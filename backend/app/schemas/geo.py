from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class UFResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    sigla: str
    nome: str
    codigo_ibge: str
    codigo_topojson: str


class MunicipioResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    codigo_ibge: str
    nome: str
    sigla_uf: str
    codigo_topojson: str
    tem_dados: bool = False
