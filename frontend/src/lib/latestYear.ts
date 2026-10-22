import type { IndicadorResponse } from '../types/api';
import { filterReliableRows } from './reliability';

export interface LatestYearSelection {
  latestYear: number | null;
  latestYearRows: IndicadorResponse[];
}

/**
 * Rows of the latest year with reliable data. API rows are one per (location, year), so
 * totals must use a single year — summing across years inflates them by the year count.
 * A partial-coverage final year is skipped (see lib/reliability.ts). Shared by KpiStrip
 * and the Hub so both show the same "Total de óbitos / internações".
 */
export function selectLatestYearRows(rows: IndicadorResponse[]): LatestYearSelection {
  if (rows.length === 0) return { latestYear: null, latestYearRows: [] };
  const reliableRows = filterReliableRows(rows, (r) => r.codigo_ibge ?? r.sigla_uf);
  const source = reliableRows.length > 0 ? reliableRows : rows;
  const latestYear = Math.max(...source.map((r) => r.ano));
  return { latestYear, latestYearRows: rows.filter((r) => r.ano === latestYear) };
}

export function sumTotalEventos(rows: IndicadorResponse[]): number {
  return rows.reduce((sum, r) => sum + (r.total_eventos ?? 0), 0);
}
