import type { ForecastResponse } from '../../types/api';

// ─── Types ────────────────────────────────────────────────────────────────────

export interface ChartDataPoint {
  ano: number;
  historico?: number;
  autoarima?: number;
  prophet?: number;
  ci80_inf?: number;
  ci80_sup?: number;
  ci95_inf?: number;
  ci95_sup?: number;
}

// ─── buildChartData ───────────────────────────────────────────────────────────

/**
 * Merges ForecastResponse.historico + modelos into a flat ChartDataPoint[].
 * One point per year, sorted ascending. Historical and forecast years may overlap
 * at ano_referencia — both values are kept on the same point without duplication.
 * CI bounds (ci80/ci95) come from the AutoARIMA model's previsoes. Missing CI
 * values from the API (null) are left undefined — never coerced to 0.
 */
export function buildChartData(resp: ForecastResponse): ChartDataPoint[] {
  const map = new Map<number, ChartDataPoint>();

  // Seed from historico
  for (const item of resp.historico) {
    if (item.valor !== null) {
      map.set(item.ano, { ano: item.ano, historico: item.valor });
    } else {
      map.set(item.ano, { ano: item.ano });
    }
  }

  // AutoARIMA — forecast values + CI bounds
  const autoarima = resp.modelos['AutoARIMA'];
  if (autoarima) {
    for (const prev of autoarima.previsoes) {
      const existing = map.get(prev.ano) ?? { ano: prev.ano };
      const update: ChartDataPoint = { ...existing, autoarima: prev.valor_previsto };
      if (prev.ci80_inf !== null && prev.ci80_inf !== undefined) update.ci80_inf = prev.ci80_inf;
      if (prev.ci80_sup !== null && prev.ci80_sup !== undefined) update.ci80_sup = prev.ci80_sup;
      if (prev.ci95_inf !== null && prev.ci95_inf !== undefined) update.ci95_inf = prev.ci95_inf;
      if (prev.ci95_sup !== null && prev.ci95_sup !== undefined) update.ci95_sup = prev.ci95_sup;
      map.set(prev.ano, update);
    }
  }

  // Prophet — forecast values only (no CI)
  const prophet = resp.modelos['Prophet'];
  if (prophet) {
    for (const prev of prophet.previsoes) {
      const existing = map.get(prev.ano) ?? { ano: prev.ano };
      map.set(prev.ano, { ...existing, prophet: prev.valor_previsto });
    }
  }

  // Sort by ano ascending
  return Array.from(map.values()).sort((a, b) => a.ano - b.ano);
}

// ─── hasForecast ─────────────────────────────────────────────────────────────

/**
 * Returns true if the response contains at least one model with at least one
 * previsao entry. Used to drive the "Previsão não disponível" notice state.
 */
export function hasForecast(resp: ForecastResponse): boolean {
  return (
    Object.keys(resp.modelos).length > 0 &&
    Object.values(resp.modelos).some((m) => m.previsoes.length > 0)
  );
}
