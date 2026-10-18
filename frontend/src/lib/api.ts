import type {
  BreakdownResponse,
  ClusterItemResponse,
  ClusterUfSummaryResponse,
  CurvaEpidemicaResponse,
  CursorPage,
  ForecastResponse,
  IndicadorResponse,
  MunicipioResponse,
  NotificacaoResponse,
  NotificacaoSummaryResponse,
  UFResponse,
} from '../types/api';
import type { FilterState } from '../store/filterStore';
import type { VigilanciaFilterState } from '../store/vigilanciaFilterStore';

export const API_BASE = import.meta.env.VITE_API_BASE_URL;

async function getJson<T>(path: string, params?: URLSearchParams): Promise<T> {
  const qs = params?.toString();
  const url = `${API_BASE}${path}${qs ? `?${qs}` : ''}`;
  const res = await fetch(url);
  if (!res.ok) {
    throw new Error(`Request failed: ${res.status} ${res.statusText} (${url})`);
  }
  return res.json() as Promise<T>;
}

/** Follows all cursor pages and returns every item. Uses next_page token from fastapi-pagination. */
async function fetchAllPages<T>(path: string, baseParams: URLSearchParams): Promise<T[]> {
  const allItems: T[] = [];
  let cursor: string | null = null;
  do {
    const params = new URLSearchParams(baseParams);
    if (cursor) params.set('cursor', cursor);
    const page = await getJson<{ items: T[]; next_page: string | null }>(path, params);
    allItems.push(...page.items);
    cursor = page.next_page ?? null;
  } while (cursor !== null);
  return allItems;
}

/**
 * GET /indicadores nivel=municipio — fetches ALL pages for the given UF.
 * RJ has 92 municipalities × 14 years ≈ 1 288 rows (~26 pages at 50/page).
 */
export async function fetchIndicadoresMunicipio(
  filters: Partial<FilterState>
): Promise<IndicadorResponse[]> {
  const params = new URLSearchParams();
  params.set('nivel', 'municipio');
  if (filters.indicador) params.set('fonte', filters.indicador);
  if (filters.uf) params.set('uf', filters.uf);
  if (filters.municipio) params.set('municipio', filters.municipio);
  if (filters.cid_capitulo) params.set('cid_capitulo', filters.cid_capitulo);
  if (filters.cid_grupo) params.set('cid_grupo', filters.cid_grupo);
  if (filters.cid_codigo) params.set('cid_codigo', filters.cid_codigo);
  if (filters.faixa_etaria) params.set('faixa_etaria', filters.faixa_etaria);
  if (filters.sexo) params.set('sexo', filters.sexo);
  if (filters.ano_inicio) params.set('ano_inicio', String(filters.ano_inicio));
  if (filters.ano_fim) params.set('ano_fim', String(filters.ano_fim));
  return fetchAllPages<IndicadorResponse>('/indicadores/', params);
}

/** GET /forecasts — municipio is the 6-digit codigo_ibge_6; metrica defaults to taxa_mortalidade_100k. */
export async function fetchForecast(
  municipio6: string,
  metrica = 'taxa_mortalidade_100k'
): Promise<ForecastResponse> {
  const params = new URLSearchParams({ municipio: municipio6, metrica });
  return getJson<ForecastResponse>('/forecasts/', params);
}

/**
 * GET /indicadores/uf-summary — returns ALL UF-year rows as a plain list (no pagination).
 * Used for national choropleth and UF time-series. Max ~400 rows.
 * CID/demographic filters are not supported here; those go through /indicadores slow path.
 */
export async function fetchIndicadoresUf(
  filters: Partial<FilterState>
): Promise<IndicadorResponse[]> {
  const params = new URLSearchParams();
  if (filters.indicador) params.set('fonte', filters.indicador);
  if (filters.uf) params.set('uf', filters.uf);
  if (filters.ano_inicio) params.set('ano_inicio', String(filters.ano_inicio));
  if (filters.ano_fim) params.set('ano_fim', String(filters.ano_fim));
  return getJson<IndicadorResponse[]>('/indicadores/uf-summary', params);
}

/**
 * GET /indicadores/uf-summary at nivel=uf — used by the time-series historical view.
 * Returns a flat list (no pagination); delegates to fetchIndicadoresUf.
 */
export async function fetchUfSeries(
  filters: Partial<FilterState>
): Promise<IndicadorResponse[]> {
  return fetchIndicadoresUf(filters);
}

/** GET /clusters — cursor-paginated CursorPage<ClusterItemResponse>. */
export async function fetchClustersPage(
  uf?: string,
  cursor?: string
): Promise<CursorPage<ClusterItemResponse>> {
  const params = new URLSearchParams();
  if (uf) params.set('uf', uf);
  if (cursor) params.set('cursor', cursor);
  return getJson<CursorPage<ClusterItemResponse>>('/clusters/', params);
}

/** GET /clusters/uf-summary — one aggregate row per UF, for the national scatter view. */
export async function fetchClustersUfSummary(): Promise<ClusterUfSummaryResponse[]> {
  return getJson<ClusterUfSummaryResponse[]>('/clusters/uf-summary');
}

/** GET /geo/ufs — cursor-paginated. */
export async function fetchUfs(cursor?: string): Promise<CursorPage<UFResponse>> {
  const params = new URLSearchParams();
  if (cursor) params.set('cursor', cursor);
  return getJson<CursorPage<UFResponse>>('/geo/ufs', params);
}

/** GET /geo/ufs/{uf}/municipios — plain list of all municipalities in the UF. */
export async function fetchMunicipios(uf: string): Promise<MunicipioResponse[]> {
  return getJson<MunicipioResponse[]>(`/geo/ufs/${uf}/municipios`);
}

/**
 * Shared param builder for every /notificacoes fetcher — kept in one place so the
 * five callers below cannot drift in filter semantics. Empty-string
 * filter values are omitted from the query string entirely.
 */
function buildNotificacoesParams(filters: Partial<VigilanciaFilterState>): URLSearchParams {
  const params = new URLSearchParams();
  if (filters.agravo) params.set('agravo', filters.agravo);
  if (filters.uf) params.set('uf', filters.uf);
  if (filters.municipio) params.set('municipio', filters.municipio);
  if (filters.classi_fin) params.set('classi_fin', filters.classi_fin);
  if (filters.ano_inicio) params.set('ano_inicio', String(filters.ano_inicio));
  if (filters.ano_fim) params.set('ano_fim', String(filters.ano_fim));
  return params;
}

/** GET /notificacoes/uf-summary — unpaginated (sigla_uf, agravo, ano) aggregate. */
export async function fetchNotificacoesUfSummary(
  filters: Partial<VigilanciaFilterState>
): Promise<NotificacaoSummaryResponse[]> {
  const params = buildNotificacoesParams(filters);
  return getJson<NotificacaoSummaryResponse[]>('/notificacoes/uf-summary', params);
}

/** GET /notificacoes/municipio-summary — unpaginated (codigo_ibge, agravo, ano) aggregate. */
export async function fetchNotificacoesMunicipioSummary(
  filters: Partial<VigilanciaFilterState>
): Promise<NotificacaoSummaryResponse[]> {
  const params = buildNotificacoesParams(filters);
  return getJson<NotificacaoSummaryResponse[]>('/notificacoes/municipio-summary', params);
}

/** GET /notificacoes/curva-epidemica — gapless series bucketed by semana epidemiológica. */
export async function fetchNotificacoesCurva(
  filters: Partial<VigilanciaFilterState>
): Promise<CurvaEpidemicaResponse[]> {
  const params = buildNotificacoesParams(filters);
  return getJson<CurvaEpidemicaResponse[]>('/notificacoes/curva-epidemica', params);
}

/** GET /notificacoes/breakdown — agravo-aware categorical aggregate for a given campo. */
export async function fetchNotificacoesBreakdown(
  filters: Partial<VigilanciaFilterState>,
  campo: string
): Promise<BreakdownResponse[]> {
  const params = buildNotificacoesParams(filters);
  params.set('campo', campo);
  return getJson<BreakdownResponse[]>('/notificacoes/breakdown', params);
}

/** GET /notificacoes — cursor-paginated raw-record drill-down; retorna só a primeira página (máx 50 registros) para evitar timeout com agravos de alto volume como DENG. */
export async function fetchNotificacoesPage(
  filters: Partial<VigilanciaFilterState>
): Promise<NotificacaoResponse[]> {
  const params = buildNotificacoesParams(filters);
  const page = await getJson<{ items: NotificacaoResponse[]; next_page: string | null }>(
    '/notificacoes/',
    params
  );
  return page.items;
}
