/**
 * VigilanciaPanel.test.tsx — smoke test for the Vigilância panel shell.
 *
 * Strategy: same convention as App.test.tsx — mock global.fetch for the UF/município
 * lookups the filter selects need, wrap render in QueryClientProvider.
 */
import React from 'react';
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter } from 'react-router-dom';

// jsdom has no ResizeObserver — @radix-ui/react-slider (used by PeriodSlider, mounted
// inside VigilanciaFilterPanel) calls it on mount. Stub it, same as App.test.tsx's
// ResponsiveContainer workaround for a jsdom-missing browser API.
class ResizeObserverStub {
  observe() {}
  unobserve() {}
  disconnect() {}
}
// eslint-disable-next-line @typescript-eslint/no-explicit-any
(global as any).ResizeObserver = ResizeObserverStub;

const emptyCursorPage = { items: [], total: null, current_page: null, current_page_backwards: null, previous_page: null, next_page: null };

global.fetch = vi.fn((url: RequestInfo | URL) => {
  const urlStr = String(url);
  if (urlStr.includes('/geo/')) {
    return Promise.resolve(new Response(JSON.stringify(emptyCursorPage), { status: 200 }));
  }
  return Promise.resolve(new Response(JSON.stringify(emptyCursorPage), { status: 200 }));
}) as typeof global.fetch;

import VigilanciaPanel from './VigilanciaPanel';
import { useVigilanciaFilterStore, VIGILANCIA_DEFAULT_STATE } from '../store/vigilanciaFilterStore';

function makeQueryClient() {
  return new QueryClient({ defaultOptions: { queries: { retry: false } } });
}

function Wrapper({ children }: { children: React.ReactNode }) {
  return (
    <QueryClientProvider client={makeQueryClient()}>
      <MemoryRouter initialEntries={['/vigilancia']}>{children}</MemoryRouter>
    </QueryClientProvider>
  );
}

describe('VigilanciaPanel', () => {
  beforeEach(() => {
    useVigilanciaFilterStore.setState({ ...VIGILANCIA_DEFAULT_STATE });
    window.history.replaceState(null, '', '/vigilancia');
  });

  afterEach(() => {
    vi.clearAllMocks();
  });

  it('renders the topbar brand', () => {
    render(<VigilanciaPanel />, { wrapper: Wrapper });
    expect(screen.getByRole('link', { name: 'HealthLens' })).toBeTruthy();
    expect(screen.getByText('· Vigilância Epidemiológica')).toBeTruthy();
  });

  it('renders the filter nav (aria-label "Filtros de vigilância")', () => {
    render(<VigilanciaPanel />, { wrapper: Wrapper });
    expect(screen.getByRole('navigation', { name: 'Filtros de vigilância' })).toBeTruthy();
  });

  it('renders the reciprocal link text', () => {
    render(<VigilanciaPanel />, { wrapper: Wrapper });
    expect(screen.getByText('· Mortalidade & Internações')).toBeTruthy();
  });

  it('renders all five region containers when agravo is DENG', () => {
    useVigilanciaFilterStore.setState({ agravo: 'DENG' });
    render(<VigilanciaPanel />, { wrapper: Wrapper });
    expect(screen.getByTestId('vigilancia-comparacao')).toBeTruthy();
    expect(screen.getByTestId('vigilancia-curva')).toBeTruthy();
    expect(screen.getByTestId('vigilancia-mapa')).toBeTruthy();
    expect(screen.getByTestId('vigilancia-breakdowns')).toBeTruthy();
    expect(screen.getByTestId('vigilancia-tabela')).toBeTruthy();
  });

  it('renders vigilancia-breakdowns (AgeSexBreakdown only, no severity section) when agravo is empty (all agravos)', () => {
    useVigilanciaFilterStore.setState({ agravo: '' });
    render(<VigilanciaPanel />, { wrapper: Wrapper });
    expect(screen.getByTestId('vigilancia-comparacao')).toBeTruthy();
    // AgeSexBreakdown renders unconditionally — the region itself
    // is present, but the agravo-gated SeverityBreakdown card title must not be.
    expect(screen.getByTestId('vigilancia-breakdowns')).toBeTruthy();
    expect(screen.queryByText('Notificações por classificação e gravidade')).toBeNull();
    expect(screen.getByText('Notificações por faixa etária e sexo')).toBeTruthy();
  });

  it('selecting Dengue on the Agravo select updates the store and keeps pathname at /vigilancia', async () => {
    const user = userEvent.setup();
    render(<VigilanciaPanel />, { wrapper: Wrapper });

    const select = screen.getByRole('combobox', { name: 'Agravo' });
    await user.selectOptions(select, 'DENG');

    expect(useVigilanciaFilterStore.getState().agravo).toBe('DENG');
    expect(window.location.pathname).toBe('/vigilancia');
  });
});
