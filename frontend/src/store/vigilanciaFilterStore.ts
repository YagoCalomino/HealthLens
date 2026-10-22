import { create } from 'zustand';
import { subscribeWithSelector } from 'zustand/middleware';

export const VIGILANCIA_DEFAULT_ANO_INICIO = 2015;
export const VIGILANCIA_DEFAULT_ANO_FIM = 2023;

export interface VigilanciaFilterState {
  agravo: 'DENG' | 'CHIK' | 'ANIM' | ''; // '' = multi-agravo comparison view
  uf: string; // '' = all
  municipio: string; // '' = all (codigo_ibge_6)
  classi_fin: string; // '' = all
  ano_inicio: number;
  ano_fim: number;
}

export interface VigilanciaFilterActions {
  setAgravo: (v: 'DENG' | 'CHIK' | 'ANIM' | '') => void;
  setUf: (v: string) => void;
  setMunicipio: (v: string) => void;
  setClassiFin: (v: string) => void;
  setAnoInicio: (v: number) => void;
  setAnoFim: (v: number) => void;
  reset: () => void;
}

export const VIGILANCIA_DEFAULT_STATE: VigilanciaFilterState = {
  agravo: '',
  uf: '',
  municipio: '',
  classi_fin: '',
  ano_inicio: VIGILANCIA_DEFAULT_ANO_INICIO,
  ano_fim: VIGILANCIA_DEFAULT_ANO_FIM,
};

export const useVigilanciaFilterStore = create<VigilanciaFilterState & VigilanciaFilterActions>()(
  subscribeWithSelector((set) => ({
    ...VIGILANCIA_DEFAULT_STATE,
    // classi_fin codes are only meaningful within one agravo's code domain
    // (DENG's 0/5/8/10/11/12 vs. CHIK's 0/5/13; ANIM has no CLASSI_FIN at all).
    setAgravo: (v) => set({ agravo: v, classi_fin: '' }),
    setUf: (v) => set({ uf: v, municipio: '' }),
    setMunicipio: (v) => set({ municipio: v.length === 7 ? v.slice(0, 6) : v }),
    setClassiFin: (v) => set({ classi_fin: v }),
    setAnoInicio: (v) => set((s) => ({ ano_inicio: Math.min(v, s.ano_fim - 1) })),
    setAnoFim: (v) => set((s) => ({ ano_fim: Math.max(v, s.ano_inicio + 1) })),
    reset: () => set({ ...VIGILANCIA_DEFAULT_STATE }),
  }))
);

/**
 * Pure param builder — kept separate from syncVigilanciaToUrl so tests can assert on the
 * resulting URLSearchParams without touching window.history.
 */
export function buildVigilanciaParams(state: VigilanciaFilterState): URLSearchParams {
  const params = new URLSearchParams();
  if (state.agravo) params.set('agravo', state.agravo);
  if (state.uf) params.set('uf', state.uf);
  if (state.municipio) params.set('municipio', state.municipio);
  if (state.classi_fin) params.set('classi_fin', state.classi_fin);
  if (state.ano_inicio !== VIGILANCIA_DEFAULT_ANO_INICIO) params.set('ano_inicio', String(state.ano_inicio));
  if (state.ano_fim !== VIGILANCIA_DEFAULT_ANO_FIM) params.set('ano_fim', String(state.ano_fim));
  return params;
}

/**
 * Writes the current filter state to the URL via history.replaceState — never a page navigation.
 * The fallback path is derived from window.location.pathname, never a hardcoded root path, so a
 * filter-clearing sync on /vigilancia cannot rewrite the URL away from its own route.
 */
export function syncVigilanciaToUrl(state: VigilanciaFilterState): void {
  const qs = buildVigilanciaParams(state).toString();
  const path = window.location.pathname;
  window.history.replaceState(null, '', qs ? `${path}?${qs}` : path);
}

/** Subscribe once (e.g. in VigilanciaPanel.tsx on mount) to keep the URL in sync with every filter change. */
export function subscribeVigilanciaUrlSync(): () => void {
  return useVigilanciaFilterStore.subscribe((state) => syncVigilanciaToUrl(state));
}

/**
 * Hydrates the store from window.location.search on initial mount.
 * Unknown params are silently ignored; agravo is validated against the literal union;
 * ano_inicio/ano_fim/classi_fin are coerced via Number with isNaN guards. No eval, no arbitrary key assignment.
 */
export function hydrateVigilanciaFromUrl(): void {
  const params = new URLSearchParams(window.location.search);
  const patch: Partial<VigilanciaFilterState> = {};

  const agravo = params.get('agravo');
  if (agravo === 'DENG' || agravo === 'CHIK' || agravo === 'ANIM' || agravo === '') patch.agravo = agravo;

  const uf = params.get('uf');
  if (uf) patch.uf = uf;

  const municipio = params.get('municipio');
  if (municipio) patch.municipio = municipio.length === 7 ? municipio.slice(0, 6) : municipio;

  const classiFin = params.get('classi_fin');
  if (classiFin !== null) {
    const cf = Number(classiFin);
    if (!Number.isNaN(cf)) patch.classi_fin = classiFin;
  }

  const ai = Number(params.get('ano_inicio'));
  if (!Number.isNaN(ai) && ai > 0) patch.ano_inicio = ai;

  const af = Number(params.get('ano_fim'));
  if (!Number.isNaN(af) && af > 0) patch.ano_fim = af;

  // Validate the full effective year range (URL values merged with defaults).
  // If the range is invalid (start >= end), reset BOTH to defaults — same guard as
  // filterStore.hydrateFromUrl (avoids clamping both slider thumbs to one position).
  const effectiveStart = patch.ano_inicio ?? VIGILANCIA_DEFAULT_STATE.ano_inicio;
  const effectiveEnd = patch.ano_fim ?? VIGILANCIA_DEFAULT_STATE.ano_fim;
  if (effectiveStart >= effectiveEnd) {
    patch.ano_inicio = VIGILANCIA_DEFAULT_STATE.ano_inicio;
    patch.ano_fim = VIGILANCIA_DEFAULT_STATE.ano_fim;
  }

  if (Object.keys(patch).length > 0) {
    useVigilanciaFilterStore.setState(patch);
  }
}
