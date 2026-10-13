"""Response contract for GET /risco-prospectivo.

All variation values (`variacao_municipio` and the peer statistics inside
`DistribuicaoPeers`) are fractional percentage changes — `0.2` means +20% —
computed as `(taxa_T3 - taxa_T) / taxa_T` over already-elapsed, actual years.
This is a retrospective comparison of real historical rates, never a
forward-looking projection: `tipo_analise` is the machine-readable framing
label the API contract requires and is always `"comparacao_prospectiva"`.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class MunicipioInfo(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    codigo_ibge_6: str
    nome_municipio: str
    sigla_uf: str


class DistribuicaoPeers(BaseModel):
    n: int
    mediana: float | None = None
    p25: float | None = None
    p75: float | None = None
    minimo: float | None = None
    maximo: float | None = None
    amostra_insuficiente: bool


class RiscoProspectivoResponse(BaseModel):
    municipio: MunicipioInfo
    ano_referencia: int
    ano_comparacao: int
    cluster_id: int
    cluster_nome: str | None = None
    variacao_municipio: float | None = None
    distribuicao_peers: DistribuicaoPeers
    tipo_analise: str = "comparacao_prospectiva"
