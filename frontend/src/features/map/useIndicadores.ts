import { useMemo } from 'react';
import { useQuery } from '@tanstack/react-query';
import { fetchIndicadoresMunicipio, fetchIndicadoresUf } from '../../lib/api';
import { useFilterStore } from '../../store/filterStore';
import type { IndicadorResponse } from '../../types/api';

const EMPTY: IndicadorResponse[] = [];

export interface UseIndicadoresResult {
  rows: IndicadorResponse[];
  /** Map keyed by codigo_ibge (7-digit where present, or sigla_uf) for O(1) lookup in ChoroplethLayer. */
  byCode: Map<string, IndicadorResponse>;
  isLoading: boolean;
  isError: boolean;
  refetch: () => void;
}

/**
 * Fetches all pages of /indicadores for the current Zustand filter state and returns
 * a flat array plus a Map for O(1) choropleth join.
 *
 * Pagination: loops on next_cursor until exhausted.  All pages are fetched in the
 * queryFn so TanStack Query's cache key covers the complete dataset.
 */
export function useIndicadores(): UseIndicadoresResult {
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

  const filters = {
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
  };

  const { data, isLoading, isError, refetch } = useQuery({
    queryKey: [
      'indicadores',
      { indicador, uf, municipio, cid_capitulo, cid_grupo, cid_codigo, faixa_etaria, sexo, ano_inicio, ano_fim },
    ],
    queryFn: async (): Promise<IndicadorResponse[]> => {
      // National view (no UF selected): single request to unpaginated endpoint.
      if (!uf) {
        return fetchIndicadoresUf(filters);
      }
      // Municipal (or UF-with-municipality-drilldown) view: follows all cursor pages internally.
      return fetchIndicadoresMunicipio(filters);
    },
    staleTime: 5 * 60 * 1000,
  });

  // Stable empty array — avoids new reference each render when data is undefined,
  // which would cause byCode useMemo to recompute and ChoroplethLayer to re-render.
  const rows = data ?? EMPTY;

  // Memoized O(1) lookup map: codigo_ibge (7-digit) → row for municipal view;
  // sigla_uf (e.g. "SP") → row for national view. New map only when rows reference changes.
  const byCode = useMemo(() => {
    const map = new Map<string, IndicadorResponse>();
    for (const row of rows) {
      if (row.codigo_ibge) map.set(row.codigo_ibge, row);
      // For sigla_uf: explicitly keep the row with the latest ano so the national choropleth
      // always shows the most recent year's rate regardless of API response ordering.
      if (row.sigla_uf) {
        const existing = map.get(row.sigla_uf);
        if (!existing || (row.ano ?? 0) > (existing.ano ?? 0)) {
          map.set(row.sigla_uf, row);
        }
      }
    }
    return map;
  }, [rows]);

  return {
    rows,
    byCode,
    isLoading,
    isError,
    refetch,
  };
}
