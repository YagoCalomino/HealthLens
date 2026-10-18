import { beforeEach, describe, expect, it } from 'vitest';
import {
  VIGILANCIA_DEFAULT_ANO_FIM,
  VIGILANCIA_DEFAULT_ANO_INICIO,
  VIGILANCIA_DEFAULT_STATE,
  buildVigilanciaParams,
  hydrateVigilanciaFromUrl,
  syncVigilanciaToUrl,
  useVigilanciaFilterStore,
} from './vigilanciaFilterStore';

beforeEach(() => {
  useVigilanciaFilterStore.setState(VIGILANCIA_DEFAULT_STATE);
  window.history.replaceState(null, '', '/vigilancia');
});

describe('useVigilanciaFilterStore cascade resets', () => {
  it('setUf resets municipio but keeps other fields untouched', () => {
    useVigilanciaFilterStore.setState({
      municipio: '355030',
      agravo: 'DENG',
      classi_fin: '10',
    });

    useVigilanciaFilterStore.getState().setUf('SP');

    const s = useVigilanciaFilterStore.getState();
    expect(s.uf).toBe('SP');
    expect(s.municipio).toBe('');
    expect(s.agravo).toBe('DENG');
    expect(s.classi_fin).toBe('10');
  });

  it('setAgravo resets classi_fin but keeps uf/municipio', () => {
    useVigilanciaFilterStore.setState({
      uf: 'SP',
      municipio: '355030',
      classi_fin: '10',
    });

    useVigilanciaFilterStore.getState().setAgravo('CHIK');

    const s = useVigilanciaFilterStore.getState();
    expect(s.agravo).toBe('CHIK');
    expect(s.classi_fin).toBe('');
    expect(s.uf).toBe('SP');
    expect(s.municipio).toBe('355030');
  });

  it('reset() returns the whole store to VIGILANCIA_DEFAULT_STATE', () => {
    useVigilanciaFilterStore.setState({
      agravo: 'DENG',
      uf: 'SP',
      municipio: '355030',
      classi_fin: '10',
      ano_inicio: 2018,
    });

    useVigilanciaFilterStore.getState().reset();

    const s = useVigilanciaFilterStore.getState();
    expect(s.agravo).toBe(VIGILANCIA_DEFAULT_STATE.agravo);
    expect(s.uf).toBe(VIGILANCIA_DEFAULT_STATE.uf);
    expect(s.municipio).toBe(VIGILANCIA_DEFAULT_STATE.municipio);
    expect(s.classi_fin).toBe(VIGILANCIA_DEFAULT_STATE.classi_fin);
    expect(s.ano_inicio).toBe(VIGILANCIA_DEFAULT_STATE.ano_inicio);
    expect(s.ano_fim).toBe(VIGILANCIA_DEFAULT_STATE.ano_fim);
  });
});

describe('setMunicipio normalization', () => {
  it('stores 6-digit code unchanged', () => {
    useVigilanciaFilterStore.getState().setMunicipio('355030');
    expect(useVigilanciaFilterStore.getState().municipio).toBe('355030');
  });

  it('truncates 7-digit codigo_ibge_7 to 6-digit codigo_ibge_6', () => {
    useVigilanciaFilterStore.getState().setMunicipio('3550305');
    expect(useVigilanciaFilterStore.getState().municipio).toBe('355030');
  });
});

describe('setAnoInicio/setAnoFim guard', () => {
  it('keeps ano_inicio < ano_fim when setting inicio above fim', () => {
    useVigilanciaFilterStore.setState({ ano_inicio: 2015, ano_fim: 2020 });
    useVigilanciaFilterStore.getState().setAnoInicio(2025);
    expect(useVigilanciaFilterStore.getState().ano_inicio).toBe(2019);
  });

  it('keeps ano_fim > ano_inicio when setting fim below inicio', () => {
    useVigilanciaFilterStore.setState({ ano_inicio: 2015, ano_fim: 2020 });
    useVigilanciaFilterStore.getState().setAnoFim(2010);
    expect(useVigilanciaFilterStore.getState().ano_fim).toBe(2016);
  });
});

describe('buildVigilanciaParams / syncVigilanciaToUrl', () => {
  it('produces an empty query string for the default state', () => {
    const params = buildVigilanciaParams(VIGILANCIA_DEFAULT_STATE);
    expect(params.toString()).toBe('');
  });

  it('only emits non-default fields as params', () => {
    const params = buildVigilanciaParams({
      ...VIGILANCIA_DEFAULT_STATE,
      agravo: 'DENG',
      uf: 'SP',
      classi_fin: '10',
    });
    const parsed = new URLSearchParams(params.toString());
    expect(parsed.get('agravo')).toBe('DENG');
    expect(parsed.get('uf')).toBe('SP');
    expect(parsed.get('classi_fin')).toBe('10');
    expect(parsed.get('municipio')).toBeNull();
    expect(parsed.get('ano_inicio')).toBeNull();
  });

  it('syncVigilanciaToUrl with no active filters keeps pathname as /vigilancia', () => {
    window.history.replaceState(null, '', '/vigilancia');
    syncVigilanciaToUrl(VIGILANCIA_DEFAULT_STATE);
    expect(window.location.pathname).toBe('/vigilancia');
    expect(window.location.search).toBe('');
  });

  it('syncVigilanciaToUrl with active filters produces pathname + query string', () => {
    window.history.replaceState(null, '', '/vigilancia');
    syncVigilanciaToUrl({ ...VIGILANCIA_DEFAULT_STATE, agravo: 'DENG', uf: 'SP' });
    expect(window.location.pathname).toBe('/vigilancia');
    expect(window.location.search).toBe('?agravo=DENG&uf=SP');
  });
});

describe('hydrateVigilanciaFromUrl', () => {
  it('accepts a valid agravo value', () => {
    window.history.replaceState(null, '', '/vigilancia?agravo=DENG');
    hydrateVigilanciaFromUrl();
    expect(useVigilanciaFilterStore.getState().agravo).toBe('DENG');
  });

  it('rejects an invalid agravo value — state stays default', () => {
    window.history.replaceState(null, '', '/vigilancia?agravo=BOGUS');
    hydrateVigilanciaFromUrl();
    expect(useVigilanciaFilterStore.getState().agravo).toBe('');
  });

  it('ignores unknown params', () => {
    window.history.replaceState(null, '', '/vigilancia?uf=SP&unknown_param=hack');
    hydrateVigilanciaFromUrl();
    const s = useVigilanciaFilterStore.getState() as unknown as Record<string, unknown>;
    expect(s.uf).toBe('SP');
    expect(s.unknown_param).toBeUndefined();
  });

  it('coerces classi_fin through Number() and ignores a non-numeric value', () => {
    window.history.replaceState(null, '', '/vigilancia?classi_fin=not-a-number');
    hydrateVigilanciaFromUrl();
    expect(useVigilanciaFilterStore.getState().classi_fin).toBe('');
  });

  it('accepts a numeric classi_fin value', () => {
    window.history.replaceState(null, '', '/vigilancia?classi_fin=10');
    hydrateVigilanciaFromUrl();
    expect(useVigilanciaFilterStore.getState().classi_fin).toBe('10');
  });

  it('leaves ano_inicio/ano_fim at defaults when absent or invalid', () => {
    window.history.replaceState(null, '', '/vigilancia?ano_inicio=not-a-number');
    hydrateVigilanciaFromUrl();
    const s = useVigilanciaFilterStore.getState();
    expect(s.ano_inicio).toBe(VIGILANCIA_DEFAULT_ANO_INICIO);
    expect(s.ano_fim).toBe(VIGILANCIA_DEFAULT_ANO_FIM);
  });

  it('resets both ano_inicio and ano_fim to defaults when the URL range is inverted', () => {
    window.history.replaceState(null, '', '/vigilancia?ano_inicio=2024&ano_fim=2015');
    hydrateVigilanciaFromUrl();
    const s = useVigilanciaFilterStore.getState();
    expect(s.ano_inicio).toBe(VIGILANCIA_DEFAULT_ANO_INICIO);
    expect(s.ano_fim).toBe(VIGILANCIA_DEFAULT_ANO_FIM);
  });
});
