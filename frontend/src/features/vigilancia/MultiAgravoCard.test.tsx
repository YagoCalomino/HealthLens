/**
 * MultiAgravoCard.test.tsx — smoke test for the 3-slot comparison card.
 *
 * Mocks useMultiAgravoComparison directly (avoids real network calls) and
 * ResponsiveContainer from recharts (jsdom has no layout engine/ResizeObserver).
 */
import React from 'react';
import { describe, it, expect, beforeEach, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';

vi.mock('./useNotificacoes', () => ({
  useMultiAgravoComparison: vi.fn(),
}));

vi.mock('recharts', async () => {
  const actual = await vi.importActual<typeof import('recharts')>('recharts');
  return {
    ...actual,
    ResponsiveContainer: ({ children }: { children: React.ReactNode }) => (
      <div data-testid="responsive-container" style={{ width: 300, height: 90 }}>
        {children}
      </div>
    ),
  };
});

import { MultiAgravoCard } from './MultiAgravoCard';
import { useMultiAgravoComparison } from './useNotificacoes';
import { useVigilanciaFilterStore, VIGILANCIA_DEFAULT_STATE } from '../../store/vigilanciaFilterStore';
import type { NotificacaoSummaryResponse } from '../../types/api';

const mockUseMultiAgravoComparison = vi.mocked(useMultiAgravoComparison);

function makeQueryClient() {
  return new QueryClient({ defaultOptions: { queries: { retry: false } } });
}

function Wrapper({ children }: { children: React.ReactNode }) {
  return <QueryClientProvider client={makeQueryClient()}>{children}</QueryClientProvider>;
}

function summaryRow(overrides: Partial<NotificacaoSummaryResponse>): NotificacaoSummaryResponse {
  return {
    sigla_uf: 'SP',
    codigo_ibge: null,
    nome_municipio: null,
    ano: 2023,
    agravo: 'DENG',
    total_notificacoes: 100,
    taxa_por_100k: 12.5,
    ...overrides,
  };
}

describe('MultiAgravoCard', () => {
  beforeEach(() => {
    useVigilanciaFilterStore.setState({ ...VIGILANCIA_DEFAULT_STATE });
    vi.clearAllMocks();
  });

  it('renders three slots with labels Dengue, Chikungunya, Animais peçonhentos when all queries are non-empty', () => {
    mockUseMultiAgravoComparison.mockReturnValue([
      { agravo: 'DENG', rows: [summaryRow({ agravo: 'DENG' })], isLoading: false, isError: false },
      { agravo: 'CHIK', rows: [summaryRow({ agravo: 'CHIK' })], isLoading: false, isError: false },
      { agravo: 'ANIM', rows: [summaryRow({ agravo: 'ANIM' })], isLoading: false, isError: false },
    ]);

    render(<MultiAgravoCard />, { wrapper: Wrapper });

    expect(screen.getByRole('button', { name: 'Dengue' })).toBeTruthy();
    expect(screen.getByRole('button', { name: 'Chikungunya' })).toBeTruthy();
    expect(screen.getByRole('button', { name: 'Animais peçonhentos' })).toBeTruthy();
  });

  it('renders the empty state for an empty DENG response while the other two still render data', () => {
    mockUseMultiAgravoComparison.mockReturnValue([
      { agravo: 'DENG', rows: [], isLoading: false, isError: false },
      { agravo: 'CHIK', rows: [summaryRow({ agravo: 'CHIK' })], isLoading: false, isError: false },
      { agravo: 'ANIM', rows: [summaryRow({ agravo: 'ANIM' })], isLoading: false, isError: false },
    ]);

    render(<MultiAgravoCard />, { wrapper: Wrapper });

    expect(screen.getByText('Nenhuma notificação encontrada')).toBeTruthy();
    // Other two slots still show their KpiCard value (12.5).
    expect(screen.getAllByText('12.5').length).toBe(2);
  });

  it('renders the error state without exposing the raw error message for a rejected query', () => {
    mockUseMultiAgravoComparison.mockReturnValue([
      { agravo: 'DENG', rows: [], isLoading: false, isError: true },
      { agravo: 'CHIK', rows: [summaryRow({ agravo: 'CHIK' })], isLoading: false, isError: false },
      { agravo: 'ANIM', rows: [summaryRow({ agravo: 'ANIM' })], isLoading: false, isError: false },
    ]);

    render(<MultiAgravoCard />, { wrapper: Wrapper });

    expect(screen.getByText('Não foi possível carregar os dados')).toBeTruthy();
    expect(screen.queryByText(/Error:/)).toBeNull();
    expect(screen.queryByText(/TypeError/)).toBeNull();
  });

  it('computes the national rate as Σ notificações / Σ população, not the sum of UF rates', () => {
    // SP: 1.000 cases / 1.000.000 people = 100/100k. AC: 300 / 100.000 = 300/100k.
    // National: 1.300 / 1.100.000 = 118,2/100k. Summing the rates would give 400.
    const rows = [
      summaryRow({ sigla_uf: 'SP', total_notificacoes: 1000, taxa_por_100k: 100 }),
      summaryRow({ sigla_uf: 'AC', total_notificacoes: 300, taxa_por_100k: 300 }),
      summaryRow({ sigla_uf: 'AC', ano: 2022, total_notificacoes: 999, taxa_por_100k: 9999 }),
    ];
    mockUseMultiAgravoComparison.mockReturnValue([
      { agravo: 'DENG', rows, isLoading: false, isError: false },
      { agravo: 'CHIK', rows: [], isLoading: false, isError: false },
      { agravo: 'ANIM', rows: [], isLoading: false, isError: false },
    ]);

    render(<MultiAgravoCard />, { wrapper: Wrapper });

    expect(screen.getByText('118.2')).toBeTruthy();
    expect(screen.queryByText('400.0')).toBeNull();
  });

  it('ANIM skips a latest year far below the usual national volume and labels the year used', () => {
    // 2023 is a partial sample (9.995 cases vs ~250k): ANIM falls back to 2020.
    const anim = [
      summaryRow({ agravo: 'ANIM', ano: 2019, total_notificacoes: 286_900, taxa_por_100k: 140 }),
      summaryRow({ agravo: 'ANIM', ano: 2020, total_notificacoes: 252_883, taxa_por_100k: 120 }),
      summaryRow({ agravo: 'ANIM', ano: 2023, total_notificacoes: 9_995, taxa_por_100k: 5 }),
    ];
    const deng = [summaryRow({ agravo: 'DENG', ano: 2023, total_notificacoes: 50, taxa_por_100k: 7 })];
    mockUseMultiAgravoComparison.mockReturnValue([
      { agravo: 'DENG', rows: deng, isLoading: false, isError: false },
      { agravo: 'CHIK', rows: [], isLoading: false, isError: false },
      { agravo: 'ANIM', rows: anim, isLoading: false, isError: false },
    ]);

    render(<MultiAgravoCard />, { wrapper: Wrapper });

    expect(screen.getByText('Animais peçonhentos · 2020')).toBeTruthy();
    expect(screen.getByText('120.0')).toBeTruthy();
    // DENG has no floor: its latest year is used even with few cases.
    expect(screen.getByText('Dengue · 2023')).toBeTruthy();
  });

  it('ANIM skips a latest year under the absolute 1.000-case floor', () => {
    const anim = [
      summaryRow({ agravo: 'ANIM', ano: 2022, total_notificacoes: 1_200, taxa_por_100k: 10 }),
      summaryRow({ agravo: 'ANIM', ano: 2023, total_notificacoes: 800, taxa_por_100k: 6 }),
    ];
    mockUseMultiAgravoComparison.mockReturnValue([
      { agravo: 'DENG', rows: [], isLoading: false, isError: false },
      { agravo: 'CHIK', rows: [], isLoading: false, isError: false },
      { agravo: 'ANIM', rows: anim, isLoading: false, isError: false },
    ]);

    render(<MultiAgravoCard />, { wrapper: Wrapper });

    expect(screen.getByText('Animais peçonhentos · 2022')).toBeTruthy();
  });

  it('clicking the Dengue slot sets the store agravo to DENG', async () => {
    mockUseMultiAgravoComparison.mockReturnValue([
      { agravo: 'DENG', rows: [summaryRow({ agravo: 'DENG' })], isLoading: false, isError: false },
      { agravo: 'CHIK', rows: [summaryRow({ agravo: 'CHIK' })], isLoading: false, isError: false },
      { agravo: 'ANIM', rows: [summaryRow({ agravo: 'ANIM' })], isLoading: false, isError: false },
    ]);

    const user = userEvent.setup();
    render(<MultiAgravoCard />, { wrapper: Wrapper });

    await user.click(screen.getByRole('button', { name: 'Dengue' }));

    expect(useVigilanciaFilterStore.getState().agravo).toBe('DENG');
  });
});
