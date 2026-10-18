import { useQuery } from '@tanstack/react-query';
import { fetchUfSeries } from '../../lib/api';
import { useFilterStore } from '../../store/filterStore';
import type { IndicadorResponse } from '../../types/api';

export interface HistoricalPoint {
  ano: number;
  taxa: number | null;
}

const EMPTY_ROWS: IndicadorResponse[] = [];

/**
 * Fetches nivel=uf time-series data and aggregates into yearly taxa_por_100k points.
 * Only active when no municipio is selected (enabled: !municipio).
 *
 * For national view (no uf): aggregates total_eventos and populacao across all 27 UFs
 * per year, then computes a population-weighted national rate.
 * For UF view (uf set): returns that UF's yearly series directly.
 */
export function useHistoricalSeries(): { series: HistoricalPoint[]; isLoading: boolean; isError: boolean } {
  const {
    indicador,
    uf,
    municipio,
    cid_capitulo,
    cid_grupo,
    cid_codigo,
    faixa_etaria,
    sexo,
    ano_inicio,
    ano_fim,
  } = useFilterStore();

  const filters = { indicador, uf, cid_capitulo, cid_grupo, cid_codigo, faixa_etaria, sexo, ano_inicio, ano_fim };

  const { data: rows = EMPTY_ROWS, isLoading, isError } = useQuery({
    queryKey: ['uf-series', { indicador, uf, cid_capitulo, cid_grupo, cid_codigo, faixa_etaria, sexo, ano_inicio, ano_fim }],
    queryFn: (): Promise<IndicadorResponse[]> => fetchUfSeries(filters),
    enabled: !municipio,
    staleTime: 5 * 60 * 1000,
  });

  // UF selected: API returns one row per year for that UF — use pre-computed taxa_por_100k
  // directly (avoids null-population issue that makes re-aggregation produce all-null taxa).
  // National: aggregate total_eventos and populacao across all 27 UFs per year.
  let series: HistoricalPoint[];
  if (uf) {
    series = rows
      .slice()
      .sort((a, b) => a.ano - b.ano)
      .map((r) => ({ ano: r.ano, taxa: r.taxa_por_100k }));
  } else {
    const byYear = new Map<number, { events: number; pop: number }>();
    for (const row of rows) {
      const prev = byYear.get(row.ano) ?? { events: 0, pop: 0 };
      byYear.set(row.ano, {
        events: prev.events + (row.total_eventos ?? 0),
        pop: prev.pop + (row.populacao ?? 0),
      });
    }
    series = Array.from(byYear.entries())
      .sort(([a], [b]) => a - b)
      .map(([ano, { events, pop }]) => ({
        ano,
        taxa: pop > 0 ? (events / pop) * 100_000 : null,
      }));
  }

  return { series, isLoading, isError };
}
