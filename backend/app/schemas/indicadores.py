from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict


class IndicadorResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    sigla_uf: str
    codigo_ibge: str | None
    nome_municipio: str | None
    ano: int
    total_eventos: int
    populacao: int | None
    taxa_por_100k: float | None
    fonte: Literal["SIM", "SIH"]
