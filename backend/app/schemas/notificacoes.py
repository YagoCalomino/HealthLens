"""Response contracts for every /notificacoes route (the routers import
these — no codebase exploration should be needed to wire them).

Vocabulary rule: SINAN has no
reliable dedup key across the 3 agravos, so fato_notificacoes is an
append-only notification log, never an asserted-confirmed-case count.
Every field name here uses `total_notificacoes` / `notificacoes` — never
the "caso[s]"-prefixed vocabulary the mortality dashboard's schemas avoid
for the same reason. Downstream UI copy must inherit this rule.
"""

from __future__ import annotations

from datetime import date
from typing import Literal

from pydantic import BaseModel, ConfigDict


class NotificacaoResponse(BaseModel):
    """Raw-record drill-down — backs GET /notificacoes cursor pages."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    agravo: Literal["DENG", "CHIK", "ANIM"]
    sigla_uf: str
    codigo_ibge: str | None
    nome_municipio: str | None
    ano: int
    mes: int | None
    dt_notific: date | None
    semana_epidemiologica: int | None
    ano_epidemiologico: int | None
    sexo: str | None
    idade_anos: int | None
    faixa_etaria: str | None
    classi_fin: int | None
    classi_fin_label: str | None
    gravidade_grave: bool | None
    tra_classi: int | None
    tra_classi_label: str | None
    tp_acidente: int | None
    tp_acidente_label: str | None
    taxa_por_100k: float | None


class NotificacaoSummaryResponse(BaseModel):
    """Aggregate sibling — deliberately field-compatible with the
    frontend's ChoroplethLayer contract (sigla_uf/codigo_ibge/nome_municipio/
    taxa_por_100k), mirroring IndicadorResponse's shape.
    """

    model_config = ConfigDict(from_attributes=True)

    sigla_uf: str
    codigo_ibge: str | None
    nome_municipio: str | None
    ano: int
    agravo: Literal["DENG", "CHIK", "ANIM"]
    total_notificacoes: int
    taxa_por_100k: float | None


class CurvaEpidemicaResponse(BaseModel):
    """Epidemic curve by semana epidemiológica."""

    model_config = ConfigDict(from_attributes=True)

    ano_epidemiologico: int
    semana_epidemiologica: int
    total_notificacoes: int
    taxa_por_100k: float | None


class BreakdownResponse(BaseModel):
    """CLASSI_FIN / gravidade / faixa etária-sexo breakdowns.

    `categoria` is the already-decoded human label (via
    app.constants.sinan.decode_*); `codigo` is the raw source code, kept for
    traceability/debugging.
    """

    model_config = ConfigDict(from_attributes=True)

    campo: str
    categoria: str | None
    codigo: int | str | None
    total_notificacoes: int
