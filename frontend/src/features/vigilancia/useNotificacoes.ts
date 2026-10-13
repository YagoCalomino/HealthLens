import { useMemo } from 'react';
import { useQueries, useQuery } from '@tanstack/react-query';
import {
  fetchNotificacoesBreakdown,
  fetchNotificacoesCurva,
  fetchNotificacoesMunicipioSummary,
  fetchNotificacoesUfSummary,
} from '../../lib/api';
import { useVigilanciaFilterStore } from '../../store/vigilanciaFilterStore';
import type {
  AgravoCodigo,
  BreakdownResponse,
  CurvaEpidemicaResponse,
  NotificacaoSummaryResponse,
} from '../../types/api';

const EMPTY_SUMMARY: NotificacaoSummaryResponse[] = [];
const EMPTY_CURVA: CurvaEpidemicaResponse[] = [];
const EMPTY_BREAKDOWN: BreakdownResponse[] = [];

/** Every /notificacoes hook reads the same filter slice from the store. */
function useVigilanciaFilters() {
  const { agravo, uf, municipio, classi_fin, ano_inicio, ano_fim } = useVigilanciaFilterStore();
  return { agravo, uf, municipio, classi_fin, ano_inicio, ano_fim };
}

/** Map keyed by codigo_ibge (or sigla_uf when codigo_ibge is null) for O(1) choropleth join. */
function toByCode(rows: NotificacaoSummaryResponse[]): Map<string, NotificacaoSummaryResponse> {
  const map = new Map<string, NotificacaoSummaryResponse>();
  for (const row of rows) {
    const key = row.codigo_ibge ?? row.sigla_uf;
    if (key) map.set(key, row);
  }
  return map;
}

export interface UseNotificacoesSummaryResult {
  rows: NotificacaoSummaryResponse[];
  byCode: Map<string, NotificacaoSummaryResponse>;
  isLoading: boolean;
  isError: boolean;
  refetch: () => void;
}

/** GET /notificacoes/uf-summary bound to the current vigilância filter state. */
export function useNotificacoesUfSummary(): UseNotificacoesSummaryResult {
  const filters = useVigilanciaFilters();
  const { data, isLoading, isError, refetch } = useQuery({
    queryKey: ['notificacoes-uf-summary', filters],
    queryFn: () => fetchNotificacoesUfSummary(filters),
    staleTime: 5 * 60 * 1000,
  });
  const rows = data ?? EMPTY_SUMMARY;
  const byCode = useMemo(() => toByCode(rows), [rows]);
  return { rows, byCode, isLoading, isError, refetch };
}

/** GET /notificacoes/municipio-summary bound to the current vigilância filter state. */
export function useNotificacoesMunicipioSummary(): UseNotificacoesSummaryResult {
  const filters = useVigilanciaFilters();
  const { data, isLoading, isError, refetch } = useQuery({
    queryKey: ['notificacoes-municipio-summary', filters],
    queryFn: () => fetchNotificacoesMunicipioSummary(filters),
    // Without a UF this would aggregate every município nationally; the choropleth
    // only consumes it at the municipal drill-down level.
    enabled: Boolean(filters.uf),
    staleTime: 5 * 60 * 1000,
  });
  const rows = data ?? EMPTY_SUMMARY;
  const byCode = useMemo(() => toByCode(rows), [rows]);
  return { rows, byCode, isLoading, isError, refetch };
}

export interface UseNotificacoesCurvaResult {
  rows: CurvaEpidemicaResponse[];
  isLoading: boolean;
  isError: boolean;
  refetch: () => void;
}

/** GET /notificacoes/curva-epidemica bound to the current vigilância filter state. */
export function useNotificacoesCurva(): UseNotificacoesCurvaResult {
  // curva-epidemica has no classi_fin param — sending it returns 422.
  const { classi_fin: _classiFin, ...filters } = useVigilanciaFilters();
  const { data, isLoading, isError, refetch } = useQuery({
    queryKey: ['notificacoes-curva', filters],
    queryFn: () => fetchNotificacoesCurva(filters),
    staleTime: 5 * 60 * 1000,
  });
  return { rows: data ?? EMPTY_CURVA, isLoading, isError, refetch };
}

export interface UseNotificacoesBreakdownResult {
  rows: BreakdownResponse[];
  isLoading: boolean;
  isError: boolean;
  refetch: () => void;
}

/** GET /notificacoes/breakdown for a given campo, bound to the current vigilância filter state. */
export function useNotificacoesBreakdown(campo: string): UseNotificacoesBreakdownResult {
  const filters = useVigilanciaFilters();
  const { data, isLoading, isError, refetch } = useQuery({
    queryKey: ['notificacoes-breakdown', campo, filters],
    queryFn: () => fetchNotificacoesBreakdown(filters, campo),
    staleTime: 5 * 60 * 1000,
  });
  return { rows: data ?? EMPTY_BREAKDOWN, isLoading, isError, refetch };
}

const COMPARISON_AGRAVOS = ['DENG', 'CHIK', 'ANIM'] as const;

export interface AgravoComparisonSlot {
  agravo: AgravoCodigo;
  rows: NotificacaoSummaryResponse[];
  isLoading: boolean;
  isError: boolean;
}

/**
 * Powers the 3-slot MultiAgravoCard. Issues exactly three parallel
 * single-agravo requests via useQueries — never a single comma-joined `agravo`
 * query param — one per code in the fixed tuple ['DENG','CHIK','ANIM'].
 *
 * Reads uf/município/período from the store but deliberately ignores the
 * store's own `agravo` field: the comparison card always shows all
 * three agravos regardless of the panel's active agravo filter.
 *
 * Uses municipio-summary when a município is selected (finer grain), otherwise
 * uf-summary — both are (…, agravo, ano) aggregates so the card can render a
 * per-ano mini series without the client re-aggregating already-paginated rows.
 */
export function useMultiAgravoComparison(): AgravoComparisonSlot[] {
  const { uf, municipio, ano_inicio, ano_fim } = useVigilanciaFilterStore();

  const results = useQueries({
    queries: COMPARISON_AGRAVOS.map((agravo) => {
      const filters = { agravo, uf, municipio, ano_inicio, ano_fim };
      return {
        queryKey: [
          municipio ? 'notificacoes-municipio-summary' : 'notificacoes-uf-summary',
          filters,
        ],
        queryFn: () =>
          municipio ? fetchNotificacoesMunicipioSummary(filters) : fetchNotificacoesUfSummary(filters),
        staleTime: 5 * 60 * 1000,
      };
    }),
  });

  return COMPARISON_AGRAVOS.map((agravo, i) => ({
    agravo,
    rows: results[i]?.data ?? EMPTY_SUMMARY,
    isLoading: results[i]?.isLoading ?? false,
    isError: results[i]?.isError ?? false,
  }));
}
