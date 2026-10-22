import { create } from 'zustand';
import { subscribeWithSelector } from 'zustand/middleware';

export const DEFAULT_ANO_INICIO = 2015;
export const DEFAULT_ANO_FIM = 2023;

export interface FilterState {
  indicador: 'SIM' | 'SIH';
  uf: string; // '' = all
  municipio: string; // '' = all (codigo_ibge_6)
  cid_capitulo: string; // '' = all
  cid_grupo: string; // '' = all
  cid_codigo: string; // '' = all
  faixa_etaria: string; // '' = all
  sexo: string; // '' = all
  ano_inicio: number;
  ano_fim: number;
}

export interface FilterActions {
  setIndicador: (v: 'SIM' | 'SIH') => void;
  setUf: (v: string) => void;
  setMunicipio: (v: string) => void;
  setCidCapitulo: (v: string) => void;
  setCidGrupo: (v: string) => void;
  setCidCodigo: (v: string) => void;
  setFaixaEtaria: (v: string) => void;
  setSexo: (v: string) => void;
  setAnoInicio: (v: number) => void;
  setAnoFim: (v: number) => void;
  reset: () => void;
}

export const DEFAULT_STATE: FilterState = {
  indicador: 'SIM',
  uf: '',
  municipio: '',
  cid_capitulo: '',
  cid_grupo: '',
  cid_codigo: '',
  faixa_etaria: '',
  sexo: '',
  ano_inicio: DEFAULT_ANO_INICIO,
  ano_fim: DEFAULT_ANO_FIM,
};

export const useFilterStore = create<FilterState & FilterActions>()(
  subscribeWithSelector((set) => ({
    ...DEFAULT_STATE,
    setIndicador: (v) =>
      set({
        indicador: v,
        cid_capitulo: '',
        cid_grupo: '',
        cid_codigo: '',
        faixa_etaria: '',
        sexo: '',
      }),
    setUf: (v) => set({ uf: v, municipio: '' }),
    setMunicipio: (v) => set({ municipio: v.length === 7 ? v.slice(0, 6) : v }),
    setCidCapitulo: (v) => set({ cid_capitulo: v, cid_grupo: '', cid_codigo: '' }),
    setCidGrupo: (v) => set({ cid_grupo: v, cid_codigo: '' }),
    setCidCodigo: (v) => set({ cid_codigo: v }),
    setFaixaEtaria: (v) => set({ faixa_etaria: v }),
    setSexo: (v) => set({ sexo: v }),
    setAnoInicio: (v) => set((s) => ({ ano_inicio: Math.min(v, s.ano_fim - 1) })),
    setAnoFim: (v) => set((s) => ({ ano_fim: Math.max(v, s.ano_inicio + 1) })),
    reset: () => set({ ...DEFAULT_STATE }),
  }))
);

/**
 * Pure param builder — kept separate from syncToUrl so tests can assert on the
 * resulting URLSearchParams without touching window.history.
 */
export function buildParams(state: FilterState): URLSearchParams {
  const params = new URLSearchParams();
  if (state.indicador !== DEFAULT_STATE.indicador) params.set('indicador', state.indicador);
  if (state.uf) params.set('uf', state.uf);
  if (state.municipio) params.set('municipio', state.municipio);
  if (state.cid_capitulo) params.set('cid_capitulo', state.cid_capitulo);
  if (state.cid_grupo) params.set('cid_grupo', state.cid_grupo);
  if (state.cid_codigo) params.set('cid_codigo', state.cid_codigo);
  if (state.faixa_etaria) params.set('faixa_etaria', state.faixa_etaria);
  if (state.sexo) params.set('sexo', state.sexo);
  if (state.ano_inicio !== DEFAULT_ANO_INICIO) params.set('ano_inicio', String(state.ano_inicio));
  if (state.ano_fim !== DEFAULT_ANO_FIM) params.set('ano_fim', String(state.ano_fim));
  return params;
}

/**
 * Writes the current filter state to the URL via history.replaceState — never a page
 * navigation. Derives its fallback from window.location.pathname (never a hardcoded '/')
 * so a filter-clearing sync on /mortalidade cannot bounce the user off to the hub.
 */
export function syncToUrl(state: FilterState): void {
  const qs = buildParams(state).toString();
  window.history.replaceState(null, '', qs ? `${window.location.pathname}?${qs}` : window.location.pathname);
}

/** Subscribe once (e.g. in App.tsx on mount) to keep the URL in sync with every filter change. */
export function subscribeUrlSync(): () => void {
  return useFilterStore.subscribe((state) => syncToUrl(state));
}

/**
 * Hydrates the store from window.location.search on initial mount.
 * Unknown params are silently ignored; indicador is validated against the literal union;
 * ano_* are coerced via Number with isNaN/positive guards. No eval, no arbitrary key assignment.
 */
export function hydrateFromUrl(): void {
  const params = new URLSearchParams(window.location.search);
  const patch: Partial<FilterState> = {};

  const ind = params.get('indicador');
  if (ind === 'SIM' || ind === 'SIH') patch.indicador = ind;

  const uf = params.get('uf');
  if (uf) patch.uf = uf;

  const municipio = params.get('municipio');
  if (municipio) patch.municipio = municipio.length === 7 ? municipio.slice(0, 6) : municipio;

  const cidCapitulo = params.get('cid_capitulo');
  if (cidCapitulo) patch.cid_capitulo = cidCapitulo;

  const cidGrupo = params.get('cid_grupo');
  if (cidGrupo) patch.cid_grupo = cidGrupo;

  const cidCodigo = params.get('cid_codigo');
  if (cidCodigo) patch.cid_codigo = cidCodigo;

  const faixaEtaria = params.get('faixa_etaria');
  if (faixaEtaria) patch.faixa_etaria = faixaEtaria;

  const sexo = params.get('sexo');
  if (sexo) patch.sexo = sexo;

  const ai = Number(params.get('ano_inicio'));
  if (!Number.isNaN(ai) && ai > 0) patch.ano_inicio = ai;

  const af = Number(params.get('ano_fim'));
  if (!Number.isNaN(af) && af > 0) patch.ano_fim = af;

  // Validate the full effective year range (URL values merged with defaults).
  // If the range is invalid (start ≥ end), reset BOTH to defaults — patching just
  // one side can produce values below min (e.g. ano_inicio = 2014 < slider min 2015),
  // causing Radix Slider to clamp both thumbs to the same position (one-handle visual).
  const effectiveStart = patch.ano_inicio ?? DEFAULT_STATE.ano_inicio;
  const effectiveEnd = patch.ano_fim ?? DEFAULT_STATE.ano_fim;
  if (effectiveStart >= effectiveEnd) {
    patch.ano_inicio = DEFAULT_STATE.ano_inicio;
    patch.ano_fim = DEFAULT_STATE.ano_fim;
  }

  if (Object.keys(patch).length > 0) {
    useFilterStore.setState(patch);
  }
}
