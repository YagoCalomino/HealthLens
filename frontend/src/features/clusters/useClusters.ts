import { useEffect } from 'react';
import { useInfiniteQuery, useQuery } from '@tanstack/react-query';
import { useFilterStore } from '../../store/filterStore';
import { fetchClustersPage, fetchClustersUfSummary } from '../../lib/api';
import type { ClusterItemResponse, ClusterUfSummaryResponse, CursorPage } from '../../types/api';

/** Common shape ClusterScatterPlot renders — município detail and UF
 * aggregate points both collapse to this before reaching the component. */
export interface ClusterPoint {
  key: string;
  label: string;
  cluster_id: number;
  cluster_nome: string | null;
  pca_x: number;
  pca_y: number;
}

export interface UseClustersResult {
  points: ClusterPoint[];
  /** 'national': one dot per UF (aggregate). 'municipal': one dot per município in the selected UF. */
  level: 'national' | 'municipal';
  isLoading: boolean;
  isFetchingNextPage: boolean;
  /** Total items fetched so far (before pca_x/y filtering) */
  total: number;
  isError: boolean;
}

/**
 * Município-grain clusters for the selected UF (two-level cluster view —
 * mirrors the choropleth's national/municipal split). Only ever
 * called when a UF is selected, so the cursor walk is bounded to one UF's
 * municípios (tens to low hundreds), not the whole country.
 */
function useMunicipioClusters(uf: string): UseClustersResult {
  const { data, fetchNextPage, hasNextPage, isFetchingNextPage, isLoading, isError } =
    useInfiniteQuery<CursorPage<ClusterItemResponse>>({
      queryKey: ['clusters', uf],
      queryFn: ({ pageParam }) => fetchClustersPage(uf, (pageParam as string | null) ?? undefined),
      initialPageParam: null as string | null,
      getNextPageParam: (lastPage) => lastPage.next_page ?? undefined,
      // Never fetches at national scope (uf === '') — that is useUfClusters'
      // job. Without this gate every município in the country would still be
      // fetched in the background on every render, defeating the point of
      // having a separate national aggregate endpoint.
      enabled: Boolean(uf),
    });

  useEffect(() => {
    if (uf && hasNextPage && !isFetchingNextPage) {
      fetchNextPage();
    }
  }, [uf, hasNextPage, isFetchingNextPage, data?.pages.length, fetchNextPage]);

  const allItems = data?.pages.flatMap((p) => p.items) ?? [];
  const points: ClusterPoint[] = allItems
    .filter((item): item is ClusterItemResponse & { pca_x: number; pca_y: number } => item.pca_x !== null && item.pca_y !== null)
    .map((item) => ({
      key: item.codigo_ibge_6,
      label: item.nome_municipio,
      cluster_id: item.cluster_id,
      cluster_nome: item.cluster_nome,
      pca_x: item.pca_x,
      pca_y: item.pca_y,
    }));

  return { points, level: 'municipal', isLoading, isFetchingNextPage, total: allItems.length, isError };
}

/** UF-grain cluster aggregates for the national (no UF selected) view. */
function useUfClusters(uf: string): UseClustersResult {
  const { data, isLoading, isError } = useQuery<ClusterUfSummaryResponse[]>({
    queryKey: ['clusters-uf-summary'],
    queryFn: fetchClustersUfSummary,
    enabled: !uf,
  });

  const rows = data ?? [];
  const points: ClusterPoint[] = rows
    .filter((row): row is ClusterUfSummaryResponse & { pca_x: number; pca_y: number } => row.pca_x !== null && row.pca_y !== null)
    .map((row) => ({
      key: row.sigla_uf,
      label: row.sigla_uf,
      cluster_id: row.cluster_id,
      cluster_nome: row.cluster_nome,
      pca_x: row.pca_x,
      pca_y: row.pca_y,
    }));

  return { points, level: 'national', isLoading, isFetchingNextPage: false, total: rows.length, isError };
}

export function useClusters(): UseClustersResult {
  const uf = useFilterStore((s) => s.uf);
  const municipal = useMunicipioClusters(uf);
  const national = useUfClusters(uf);

  // Hooks above always run (rules-of-hooks) — only one result is used per render.
  return uf ? municipal : national;
}
