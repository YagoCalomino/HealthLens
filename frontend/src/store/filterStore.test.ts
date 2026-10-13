import { beforeEach, describe, expect, it } from 'vitest';
import {
  DEFAULT_ANO_FIM,
  DEFAULT_ANO_INICIO,
  DEFAULT_STATE,
  buildParams,
  hydrateFromUrl,
  syncToUrl,
  useFilterStore,
} from './filterStore';

beforeEach(() => {
  useFilterStore.setState(DEFAULT_STATE);
  window.history.replaceState(null, '', '/mortalidade');
});

describe('useFilterStore cascade resets', () => {
  it('setIndicador resets cid_*/faixa_etaria/sexo but preserves uf/municipio/ano_inicio/ano_fim', () => {
    useFilterStore.setState({
      uf: 'SP',
      municipio: '355030',
      cid_capitulo: 'IX',
      cid_grupo: 'I20-I25',
      cid_codigo: 'I21',
      faixa_etaria: '60+',
      sexo: 'M',
      ano_inicio: 2015,
      ano_fim: 2020,
    });

    useFilterStore.getState().setIndicador('SIH');

    const s = useFilterStore.getState();
    expect(s.indicador).toBe('SIH');
    expect(s.uf).toBe('SP');
    expect(s.municipio).toBe('355030');
    expect(s.cid_capitulo).toBe('');
    expect(s.cid_grupo).toBe('');
    expect(s.cid_codigo).toBe('');
    expect(s.faixa_etaria).toBe('');
    expect(s.sexo).toBe('');
    expect(s.ano_inicio).toBe(2015);
    expect(s.ano_fim).toBe(2020);
  });

  it('setUf resets municipio but keeps cid_* untouched', () => {
    useFilterStore.setState({
      municipio: '355030',
      cid_capitulo: 'IX',
      cid_grupo: 'I20-I25',
      cid_codigo: 'I21',
    });

    useFilterStore.getState().setUf('SP');

    const s = useFilterStore.getState();
    expect(s.uf).toBe('SP');
    expect(s.municipio).toBe('');
    expect(s.cid_capitulo).toBe('IX');
    expect(s.cid_grupo).toBe('I20-I25');
    expect(s.cid_codigo).toBe('I21');
  });

  it('setCidCapitulo resets cid_grupo and cid_codigo', () => {
    useFilterStore.setState({ cid_grupo: 'I20-I25', cid_codigo: 'I21' });

    useFilterStore.getState().setCidCapitulo('IX');

    const s = useFilterStore.getState();
    expect(s.cid_capitulo).toBe('IX');
    expect(s.cid_grupo).toBe('');
    expect(s.cid_codigo).toBe('');
  });

  it('setCidGrupo resets cid_codigo but keeps cid_capitulo', () => {
    useFilterStore.setState({ cid_capitulo: 'IX', cid_codigo: 'I21' });

    useFilterStore.getState().setCidGrupo('I20-I25');

    const s = useFilterStore.getState();
    expect(s.cid_capitulo).toBe('IX');
    expect(s.cid_grupo).toBe('I20-I25');
    expect(s.cid_codigo).toBe('');
  });

  it('setCidCodigo does not reset any other field', () => {
    useFilterStore.setState({
      uf: 'SP',
      municipio: '355030',
      cid_capitulo: 'IX',
      cid_grupo: 'I20-I25',
      faixa_etaria: '60+',
      sexo: 'M',
    });

    useFilterStore.getState().setCidCodigo('I21');

    const s = useFilterStore.getState();
    expect(s.cid_codigo).toBe('I21');
    expect(s.uf).toBe('SP');
    expect(s.municipio).toBe('355030');
    expect(s.cid_capitulo).toBe('IX');
    expect(s.cid_grupo).toBe('I20-I25');
    expect(s.faixa_etaria).toBe('60+');
    expect(s.sexo).toBe('M');
  });

  it('reset() returns the whole store to DEFAULT_STATE', () => {
    useFilterStore.setState({
      indicador: 'SIH',
      uf: 'SP',
      municipio: '355030',
      cid_capitulo: 'IX',
      ano_inicio: 2018,
    });

    useFilterStore.getState().reset();

    const s = useFilterStore.getState();
    expect(s.indicador).toBe(DEFAULT_STATE.indicador);
    expect(s.uf).toBe(DEFAULT_STATE.uf);
    expect(s.municipio).toBe(DEFAULT_STATE.municipio);
    expect(s.cid_capitulo).toBe(DEFAULT_STATE.cid_capitulo);
    expect(s.ano_inicio).toBe(DEFAULT_STATE.ano_inicio);
    expect(s.ano_fim).toBe(DEFAULT_STATE.ano_fim);
  });
});

describe('setMunicipio normalization', () => {
  it('stores 6-digit code unchanged', () => {
    useFilterStore.getState().setMunicipio('355030');
    expect(useFilterStore.getState().municipio).toBe('355030');
  });

  it('truncates 7-digit codigo_ibge_7 to 6-digit codigo_ibge_6', () => {
    useFilterStore.getState().setMunicipio('3550305');
    expect(useFilterStore.getState().municipio).toBe('355030');
  });
});

describe('hydrateFromUrl municipio normalization', () => {
  it('truncates 7-digit municipio from URL to 6-digit', () => {
    window.history.replaceState(null, '', '?uf=SP&municipio=3550305');
    hydrateFromUrl();
    expect(useFilterStore.getState().municipio).toBe('355030');
  });

  it('preserves 6-digit municipio from URL unchanged', () => {
    window.history.replaceState(null, '', '?uf=SP&municipio=355030');
    hydrateFromUrl();
    expect(useFilterStore.getState().municipio).toBe('355030');
  });
});

describe('buildParams / syncToUrl', () => {
  it('produces an empty query string for the default state', () => {
    const params = buildParams(DEFAULT_STATE);
    expect(params.toString()).toBe('');
  });

  it('only emits non-default fields as params', () => {
    const params = buildParams({
      ...DEFAULT_STATE,
      uf: 'SP',
      cid_capitulo: 'IX',
      cid_codigo: 'I21',
    });
    const parsed = new URLSearchParams(params.toString());
    expect(parsed.get('uf')).toBe('SP');
    expect(parsed.get('cid_capitulo')).toBe('IX');
    expect(parsed.get('cid_codigo')).toBe('I21');
    expect(parsed.get('cid_grupo')).toBeNull();
    expect(parsed.get('indicador')).toBeNull();
    expect(parsed.get('municipio')).toBeNull();
  });

  it('never string-concatenates raw values — special chars are auto-encoded via URLSearchParams', () => {
    const params = buildParams({
      ...DEFAULT_STATE,
      uf: 'S&P=X',
    });
    // URLSearchParams encodes '&' and '=' so they cannot be (mis)interpreted as param separators.
    expect(params.toString()).toContain('uf=S%26P%3DX');
    const parsed = new URLSearchParams(params.toString());
    expect(parsed.get('uf')).toBe('S&P=X');
  });

  it('syncToUrl(DEFAULT_STATE) preserves the current pathname instead of rewriting to /', () => {
    window.history.replaceState(null, '', '/mortalidade?uf=SP');

    syncToUrl(DEFAULT_STATE);

    expect(window.location.pathname).toBe('/mortalidade');
    expect(window.location.search).toBe('');
  });

  it('syncToUrl with active filters produces /mortalidade?uf=SP&...', () => {
    window.history.replaceState(null, '', '/mortalidade');

    syncToUrl({ ...DEFAULT_STATE, uf: 'SP' });

    expect(window.location.pathname).toBe('/mortalidade');
    expect(window.location.search).toBe('?uf=SP');
  });

  it('syncToUrl never navigates off a non-root pathname (e.g. /vigilancia)', () => {
    window.history.replaceState(null, '', '/vigilancia?uf=RJ');

    syncToUrl(DEFAULT_STATE);

    expect(window.location.pathname).toBe('/vigilancia');
  });
});

describe('hydrateFromUrl', () => {
  it('parses uf, indicador, ano_inicio from the URL and sets store state', () => {
    window.history.replaceState(null, '', '?uf=SP&indicador=SIH&ano_inicio=2015');

    hydrateFromUrl();

    const s = useFilterStore.getState();
    expect(s.uf).toBe('SP');
    expect(s.indicador).toBe('SIH');
    expect(s.ano_inicio).toBe(2015);
  });

  it('ignores unknown params', () => {
    window.history.replaceState(null, '', '?uf=SP&unknown_param=hack');

    hydrateFromUrl();

    const s = useFilterStore.getState() as unknown as Record<string, unknown>;
    expect(s.uf).toBe('SP');
    expect(s.unknown_param).toBeUndefined();
  });

  it('ignores an invalid indicador value', () => {
    window.history.replaceState(null, '', '?indicador=INVALID');

    hydrateFromUrl();

    const s = useFilterStore.getState();
    expect(s.indicador).toBe(DEFAULT_STATE.indicador);
  });

  it('leaves ano_inicio/ano_fim at defaults when absent or invalid', () => {
    window.history.replaceState(null, '', '?ano_inicio=not-a-number');

    hydrateFromUrl();

    const s = useFilterStore.getState();
    expect(s.ano_inicio).toBe(DEFAULT_ANO_INICIO);
    expect(s.ano_fim).toBe(DEFAULT_ANO_FIM);
  });
});
