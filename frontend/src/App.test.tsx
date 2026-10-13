/**
 * App.test.tsx — Integration smoke test for the full dashboard assembly.
 *
 * Strategy:
 * - Mock network-bound children that need a browser SVG environment
 *   (react-simple-maps, recharts ResponsiveContainer → lightweight stubs)
 * - Mock global.fetch to return minimal valid API responses
 * - Wrap render in QueryClientProvider with a fresh QueryClient
 *
 * Assertions (deterministic, no SVG paint):
 * 1. Header brand "HealthLens" renders
 * 2. FilterPanel (aria-label "Painel de filtros") renders
 * 3. hydrateFromUrl applied — ?uf=SP&indicador=SIH hydrates the store
 * 4. Mapa/Tabela toggle button (aria-label "Alternar entre mapa e tabela") is present
 */
import React from 'react';
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter } from 'react-router-dom';

// ─── Mock react-simple-maps ───────────────────────────────────────────────────
// MapView internally uses ComposableMap / Geographies / Geography from
// react-simple-maps which requires an SVG browser environment.
// We stub them with lightweight divs so jsdom doesn't break.
vi.mock('react-simple-maps', () => ({
  ComposableMap: ({ children }: { children?: React.ReactNode }) => (
    <div data-testid="composable-map">{children}</div>
  ),
  Geographies: ({ children }: { children: (args: { geographies: unknown[] }) => React.ReactNode }) =>
    children({ geographies: [] }),
  Geography: () => <path data-testid="geography" />,
  ZoomableGroup: ({ children }: { children?: React.ReactNode }) => <g>{children}</g>,
}));

// ─── Mock recharts ResponsiveContainer ───────────────────────────────────────
// ResponsiveContainer calls ResizeObserver which jsdom does not provide.
// Replace it with a fixed-size div stub so chart children render.
vi.mock('recharts', async (importOriginal) => {
  const actual = await importOriginal<typeof import('recharts')>();
  return {
    ...actual,
    ResponsiveContainer: ({ children }: { children?: React.ReactNode }) => (
      <div data-testid="responsive-container" style={{ width: 600, height: 320 }}>
        {children}
      </div>
    ),
  };
});

// ─── Mock API fetch ───────────────────────────────────────────────────────────
const emptyCursorPage = { items: [], total: null, current_page: null, current_page_backwards: null, previous_page: null, next_page: null };
const mockForecastResponse = {
  municipio: { codigo_ibge_6: '350330', nome_municipio: 'São Paulo', sigla_uf: 'SP' },
  metrica: 'SIM',
  ano_referencia: 2022,
  historico: [],
  modelos: {},
};
const cid10Json = [
  {
    id: 'IX',
    descricao: 'Doenças do aparelho circulatório',
    grupos: [],
  },
];

global.fetch = vi.fn((url: RequestInfo | URL) => {
  const urlStr = String(url);

  // CID-10 hierarchy (served as static JSON by Vite)
  if (urlStr.includes('cid10_hierarchy')) {
    return Promise.resolve(
      new Response(JSON.stringify(cid10Json), { status: 200 })
    );
  }

  // /geo/ufs and /geo/municipios (FilterPanel)
  if (urlStr.includes('/geo/')) {
    return Promise.resolve(
      new Response(JSON.stringify(emptyCursorPage), { status: 200 })
    );
  }

  // /indicadores/uf-summary — plain list (no pagination)
  if (urlStr.includes('/indicadores/uf-summary')) {
    return Promise.resolve(
      new Response(JSON.stringify([]), { status: 200 })
    );
  }
  // /indicadores — cursor-paginated (municipio view)
  if (urlStr.includes('/indicadores')) {
    return Promise.resolve(
      new Response(JSON.stringify(emptyCursorPage), { status: 200 })
    );
  }

  // /forecasts (TimeSeriesChart)
  if (urlStr.includes('/forecasts')) {
    return Promise.resolve(
      new Response(JSON.stringify(mockForecastResponse), { status: 200 })
    );
  }

  // /clusters (ClusterScatterPlot)
  if (urlStr.includes('/clusters')) {
    return Promise.resolve(
      new Response(JSON.stringify(emptyCursorPage), { status: 200 })
    );
  }

  // Default: empty page
  return Promise.resolve(
    new Response(JSON.stringify(emptyCursorPage), { status: 200 })
  );
}) as typeof global.fetch;

// ─── Import App after mocks are set up ───────────────────────────────────────
import App from './App';
import { useFilterStore, DEFAULT_STATE, hydrateFromUrl } from './store/filterStore';

function makeQueryClient() {
  return new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
}

function Wrapper({ children }: { children: React.ReactNode }) {
  return (
    <QueryClientProvider client={makeQueryClient()}>
      <MemoryRouter initialEntries={['/mortalidade']}>{children}</MemoryRouter>
    </QueryClientProvider>
  );
}

describe('App integration smoke test', () => {
  beforeEach(() => {
    // Reset store to default before each test
    useFilterStore.setState({ ...DEFAULT_STATE });
  });

  afterEach(() => {
    vi.clearAllMocks();
  });

  it('renders the header brand "HealthLens"', () => {
    render(<App />, { wrapper: Wrapper });
    expect(screen.getByText('HealthLens')).toBeTruthy();
  });

  it('renders the FilterPanel (aria-label "Painel de filtros")', () => {
    render(<App />, { wrapper: Wrapper });
    const panel = screen.getByRole('navigation', { name: 'Painel de filtros' });
    expect(panel).toBeTruthy();
  });

  it('hydrateFromUrl — ?uf=SP&indicador=SIH sets store.uf and store.indicador', () => {
    // Reset store to defaults first so prior module-level hydrateFromUrl doesn't interfere
    useFilterStore.setState({ ...DEFAULT_STATE });

    // Simulate a page load with URL params by updating window.location.search
    // and calling hydrateFromUrl explicitly (the module-level call already fired;
    // here we simulate a second call as if the page were freshly loaded at this URL).
    Object.defineProperty(window, 'location', {
      value: { ...window.location, search: '?uf=SP&indicador=SIH' },
      writable: true,
      configurable: true,
    });

    hydrateFromUrl();

    expect(useFilterStore.getState().uf).toBe('SP');
    expect(useFilterStore.getState().indicador).toBe('SIH');
  });

  it('renders the Mapa/Tabela toggle button', () => {
    render(<App />, { wrapper: Wrapper });
    const toggleBtn = screen.getByRole('button', { name: 'Alternar entre mapa e tabela' });
    expect(toggleBtn).toBeTruthy();
  });
});
