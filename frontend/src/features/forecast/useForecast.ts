import { useQuery } from '@tanstack/react-query';
import { fetchForecast } from '../../lib/api';
import { useFilterStore } from '../../store/filterStore';

// ─── useForecast ──────────────────────────────────────────────────────────────

/**
 * Fetches the /forecasts endpoint for the municipio currently selected in the
 * filter store. Returns hasMunicipio=false when no municipio is selected so the
 * chart can render the "Selecione um município" empty state without triggering
 * a request. Caches aggressively (staleTime 10 min) because forecasts are
 * pre-computed offline and do not change between API restarts.
 */
export function useForecast() {
  const municipio = useFilterStore((s) => s.municipio);

  const { data, isLoading, isError } = useQuery({
    queryKey: ['forecasts', municipio],
    queryFn: () => fetchForecast(municipio),
    enabled: !!municipio,
    staleTime: 10 * 60 * 1000,
  });

  return {
    data,
    isLoading,
    isError,
    hasMunicipio: !!municipio,
  };
}
