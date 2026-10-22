import React from 'react';
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter, Routes, Route, useLocation } from 'react-router-dom';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import Hub from './Hub';

// SIM: latest year 2023 → 200 + 50 = 250. SIH: 2023 → 1.000 + 234 = 1.234.
// SINAN (all three agravos, default period): 1.000 + 500 + 300 + 200 = 2.000.
const INDICADORES: Record<string, object[]> = {
  SIM: [
    { sigla_uf: 'SP', codigo_ibge: null, nome_municipio: null, ano: 2022, total_eventos: 100, populacao: 1000, taxa_por_100k: 1, fonte: 'SIM' },
    { sigla_uf: 'SP', codigo_ibge: null, nome_municipio: null, ano: 2023, total_eventos: 200, populacao: 1000, taxa_por_100k: 1, fonte: 'SIM' },
    { sigla_uf: 'RJ', codigo_ibge: null, nome_municipio: null, ano: 2023, total_eventos: 50, populacao: 1000, taxa_por_100k: 1, fonte: 'SIM' },
  ],
  SIH: [
    { sigla_uf: 'SP', codigo_ibge: null, nome_municipio: null, ano: 2023, total_eventos: 1000, populacao: 1000, taxa_por_100k: 1, fonte: 'SIH' },
    { sigla_uf: 'RJ', codigo_ibge: null, nome_municipio: null, ano: 2023, total_eventos: 234, populacao: 1000, taxa_por_100k: 1, fonte: 'SIH' },
  ],
};

const NOTIFICACOES: Record<string, number[]> = { DENG: [1000, 500], CHIK: [300], ANIM: [200] };

function mockFetch(url: RequestInfo | URL): Promise<Response> {
  const parsed = new URL(String(url), 'http://test');
  let body: unknown = [];
  if (parsed.pathname.endsWith('/indicadores/uf-summary')) {
    body = INDICADORES[parsed.searchParams.get('fonte') ?? ''] ?? [];
  } else if (parsed.pathname.endsWith('/notificacoes/uf-summary')) {
    const agravo = parsed.searchParams.get('agravo') ?? '';
    body = (NOTIFICACOES[agravo] ?? []).map((total, i) => ({
      sigla_uf: 'SP', codigo_ibge: null, nome_municipio: null, ano: 2015 + i, agravo,
      total_notificacoes: total, taxa_por_100k: 1,
    }));
  }
  return Promise.resolve({ ok: true, json: () => Promise.resolve(body) } as Response);
}

function withQueryClient(ui: React.ReactElement) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return <QueryClientProvider client={client}>{ui}</QueryClientProvider>;
}

function LocationProbe() {
  const location = useLocation();
  return <div data-testid="location-probe">{location.pathname}</div>;
}

function renderHub() {
  return render(
    withQueryClient(
      <MemoryRouter>
        <Hub />
      </MemoryRouter>
    )
  );
}

function renderHubWithRoutes() {
  return render(
    withQueryClient(
      <MemoryRouter initialEntries={['/']}>
        <Routes>
          <Route path="/" element={<Hub />} />
          <Route path="/mortalidade" element={<LocationProbe />} />
          <Route path="/vigilancia" element={<LocationProbe />} />
        </Routes>
      </MemoryRouter>
    )
  );
}

describe('Hub', () => {
  beforeEach(() => {
    global.fetch = vi.fn(mockFetch) as unknown as typeof fetch;
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it('renders exactly two cards with the expected headings', () => {
    renderHub();
    expect(screen.getByRole('heading', { name: 'Mortalidade & Internações' })).toBeTruthy();
    expect(screen.getByRole('heading', { name: 'Vigilância Epidemiológica' })).toBeTruthy();
  });

  it('renders the card 1 description text', () => {
    renderHub();
    expect(
      screen.getByText(
        'Óbitos e internações do SUS por local, tempo e causa, com série temporal, previsão AutoARIMA e agrupamento K-Means por estado.'
      )
    ).toBeTruthy();
  });

  it('renders the card 2 description text', () => {
    renderHub();
    expect(
      screen.getByText(
        'Notificações SINAN de dengue, chikungunya e animais peçonhentos, com curva epidêmica semanal e perfil demográfico.'
      )
    ).toBeTruthy();
  });

  // The reciprocal sibling-route link was removed in the Hub redesign.
  it.skip('renders a discreet reciprocal <a> link on each card to the sibling route', () => {
    renderHub();
    const links = screen.getAllByRole('link');
    const hrefs = links.map((l) => l.getAttribute('href'));
    expect(hrefs).toContain('/mortalidade');
    expect(hrefs).toContain('/vigilancia');
  });

  it('never nests an <a> inside another <a> (invalid DOM — breaks click/history behavior)', () => {
    const { container } = renderHub();
    // Card bodies are clickable via role="link" divs, not real anchors, specifically
    // so the reciprocal <Link> inside each card never lands inside a real <a>.
    expect(container.querySelectorAll('a a').length).toBe(0);
  });

  it('clicking card 1 navigates to /mortalidade', async () => {
    const user = userEvent.setup();
    renderHubWithRoutes();
    await user.click(screen.getByRole('heading', { name: 'Mortalidade & Internações' }));
    expect((await screen.findByTestId('location-probe')).textContent).toBe('/mortalidade');
  });

  it('pressing Enter on card 2 (focused) navigates to /vigilancia', async () => {
    const user = userEvent.setup();
    renderHubWithRoutes();
    const card = screen.getByText('Vigilância Epidemiológica').closest('[role="link"]');
    expect(card).toBeTruthy();
    (card as HTMLElement).focus();
    await user.keyboard('{Enter}');
    expect((await screen.findByTestId('location-probe')).textContent).toBe('/vigilancia');
  });

  // The reciprocal sibling-route link was removed in the Hub redesign.
  it.skip('clicking the reciprocal link on card 1 navigates to /vigilancia, not /mortalidade', async () => {
    const user = userEvent.setup();
    renderHubWithRoutes();
    await user.click(screen.getByText('→ Vigilância Epidemiológica'));
    expect((await screen.findByTestId('location-probe')).textContent).toBe('/vigilancia');
  });

  it('shows latest-year óbitos and internações totals from /indicadores, like the dashboard KPI', async () => {
    renderHub();
    expect(await screen.findByText('250')).toBeTruthy();
    expect(screen.getByText('Óbitos em 2023')).toBeTruthy();
    expect(await screen.findByText('1.234')).toBeTruthy();
    expect(screen.getByText('Internações em 2023')).toBeTruthy();
  });

  it('shows total SINAN notificações summed across the three agravos for the default period', async () => {
    renderHub();
    expect(await screen.findByText('2.000')).toBeTruthy();
    expect(screen.getByText('Notificações SINAN · 2015–2024')).toBeTruthy();
  });

  it('shows a dash instead of a number when the API fails', async () => {
    global.fetch = vi.fn(() =>
      Promise.resolve({ ok: false, status: 500, statusText: 'err', json: () => Promise.resolve({}) } as Response)
    ) as unknown as typeof fetch;
    renderHub();
    expect((await screen.findAllByText('—')).length).toBe(3);
  });
});
