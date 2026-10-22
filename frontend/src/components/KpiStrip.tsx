import React from 'react';
import type { IndicadorResponse, ForecastResponse } from '../types/api';
import { filterReliableRows } from '../lib/reliability';
import { selectLatestYearRows, sumTotalEventos } from '../lib/latestYear';
import { KpiCard } from './KpiCard';

// ---------------------------------------------------------------------------
// KpiStrip — exported component
// ---------------------------------------------------------------------------

export interface KpiStripProps {
  rows: IndicadorResponse[];
  forecasts?: ForecastResponse | null;
  uf: string;
  municipio: string;
  anoInicio: number;
  anoFim: number;
  indicador: 'SIM' | 'SIH';
  /** Denominator for KPI #3 — 27 UFs nationally, or the UF's municipality count when drilled in. */
  coberturaTotal: number;
}

export function KpiStrip({
  rows,
  forecasts,
  uf,
  municipio,
  anoInicio,
  anoFim,
  indicador,
  coberturaTotal,
}: KpiStripProps): React.ReactElement {
  // KPI #1 and #2 reflect only the latest reliable year (see lib/latestYear.ts).
  const { latestYearRows } = selectLatestYearRows(rows);

  // -------------------------------------------------------------------------
  // KPI #1 — Total, latest year only
  // -------------------------------------------------------------------------
  const totalValue =
    latestYearRows.length === 0
      ? '—'
      : sumTotalEventos(latestYearRows).toLocaleString('pt-BR', { maximumFractionDigits: 0 });
  const kpi1Label = indicador === 'SIM' ? 'Total de óbitos' : 'Total de internações';

  // -------------------------------------------------------------------------
  // KPI #2 — Taxa média (population-weighted, latest year only)
  // -------------------------------------------------------------------------
  const latestYearRowsWithPop = latestYearRows.filter((r) => r.populacao != null && r.populacao > 0);
  const somaEventos = latestYearRowsWithPop.reduce((s, r) => s + (r.total_eventos ?? 0), 0);
  const somaPopulacao = latestYearRowsWithPop.reduce((s, r) => s + r.populacao!, 0);
  const taxaMedia = somaPopulacao === 0 ? null : (somaEventos / somaPopulacao) * 100000;
  const kpi2Value = taxaMedia == null ? '—' : taxaMedia.toFixed(1);

  // -------------------------------------------------------------------------
  // KPI #3 — Cobertura
  // -------------------------------------------------------------------------
  const coberturaLabel = uf ? 'COBERTURA · MUNICÍPIOS' : 'COBERTURA · ESTADOS';
  const coberturaComDados = uf
    ? new Set(rows.filter((r) => r.codigo_ibge != null).map((r) => r.codigo_ibge!)).size
    : new Set(rows.map((r) => r.sigla_uf)).size;
  const kpi3Value = coberturaTotal === 0 ? '—' : `${coberturaComDados}/${coberturaTotal}`;

  // -------------------------------------------------------------------------
  // KPI #4 — Previsão / Variação (three-way)
  // -------------------------------------------------------------------------
  const prophet = forecasts?.modelos?.['Prophet'];
  const previsoes = prophet?.previsoes ?? [];

  const lastForecastVal = previsoes.length > 0 ? previsoes[previsoes.length - 1]!.valor_previsto : null;

  let forecastDelta: string | undefined;
  let forecastDeltaColor: string | undefined;
  if (previsoes.length >= 2) {
    const prev = previsoes[previsoes.length - 2].valor_previsto;
    const curr = previsoes[previsoes.length - 1].valor_previsto;
    const pct = prev !== 0 ? ((curr - prev) / Math.abs(prev)) * 100 : 0;
    const direction = pct >= 0 ? 'up' : 'down';
    // Increase in mortality/hospitalization rate is epidemiologically bad → --neg
    forecastDeltaColor = direction === 'up' ? 'var(--neg)' : 'var(--pos)';
    forecastDelta = `${direction === 'up' ? '▲' : '▼'} ${Math.abs(pct).toFixed(1)}%`;
  }

  // National variation: percent change from first to last year in rows
  const isNational = !municipio && !uf;
  let variationValue: string | null = null;
  let variationDelta: string | undefined;
  let variationDeltaColor: string | undefined;

  if (isNational && rows.length > 0) {
    // Exclude partial-coverage years so a near-zero baseline doesn't blow up the
    // percentage — same per-location median guard as trendByKey in App.tsx.
    const reliable = filterReliableRows(rows, (r) => r.codigo_ibge ?? r.sigla_uf);
    const sorted = reliable.slice().sort((a, b) => a.ano - b.ano);
    const firstTaxa = sorted.length >= 2 ? sorted[0]?.taxa_por_100k : null;
    const lastTaxa = sorted.length >= 2 ? sorted[sorted.length - 1]?.taxa_por_100k : null;
    if (firstTaxa != null && lastTaxa != null && firstTaxa !== 0) {
      const pct = ((lastTaxa - firstTaxa) / Math.abs(firstTaxa)) * 100;
      variationValue = `${pct >= 0 ? '+' : ''}${pct.toFixed(1)}%`;
      const direction = pct >= 0 ? 'up' : 'down';
      variationDeltaColor = direction === 'up' ? 'var(--neg)' : 'var(--pos)';
      variationDelta = `${direction === 'up' ? '▲' : '▼'} ${Math.abs(pct).toFixed(1)}%`;
    }
  }

  // Resolve KPI #4 display based on selection context
  const isForecastCard = !isNational;
  const nextYear = previsoes.length > 0 ? previsoes[0]!.ano : null;
  const kpi4Label = municipio
    ? `Previsão · próx. ano${nextYear ? ` · ${nextYear}` : ''}`
    : uf
    ? `Previsão UF · ${uf}${nextYear ? ` · ${nextYear}` : ''}`
    : `Variação · ${anoInicio}–${anoFim}`;

  const kpi4Value = isNational
    ? (variationValue ?? '—')
    : lastForecastVal != null
    ? lastForecastVal.toFixed(1)
    : '—';

  const kpi4Delta = isNational ? variationDelta : forecastDelta;
  const kpi4DeltaColor = isNational ? variationDeltaColor : forecastDeltaColor;

  // Two groups that match the mid-row column proportions (flex: 1.15 / flex: 1)
  return (
    <div style={{ display: 'flex', gap: 10, minWidth: 0 }}>
      <div style={{ flex: 1.15, minWidth: 0, display: 'flex', gap: 10 }}>
        <KpiCard label={kpi1Label} value={totalValue} />
        <KpiCard label="Taxa média · por 100k" value={kpi2Value} />
      </div>
      <div style={{ flex: 1, minWidth: 0, display: 'flex', gap: 10 }}>
        <KpiCard label={coberturaLabel} value={kpi3Value} />
        <KpiCard
          label={kpi4Label}
          value={kpi4Value}
          delta={kpi4Delta}
          deltaColor={kpi4DeltaColor}
          isForecast={isForecastCard}
        />
      </div>
    </div>
  );
}
