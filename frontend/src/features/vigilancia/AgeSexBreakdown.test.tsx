/**
 * AgeSexBreakdown.test.tsx — always-on faixa_etaria/sexo breakdown.
 *
 * Mocks useNotificacoesBreakdown directly (avoids real network calls) and
 * ResponsiveContainer from recharts (jsdom has no layout engine/ResizeObserver).
 */
import React from 'react';
import { describe, it, expect, beforeEach, vi } from 'vitest';
import { render, screen } from '@testing-library/react';

vi.mock('./useNotificacoes', () => ({
  useNotificacoesBreakdown: vi.fn(),
}));

vi.mock('recharts', async () => {
  const actual = await vi.importActual<typeof import('recharts')>('recharts');
  return {
    ...actual,
    ResponsiveContainer: ({ children }: { children: React.ReactNode }) => (
      <div data-testid="responsive-container" style={{ width: 500, height: 200 }}>
        {children}
      </div>
    ),
  };
});

import { AgeSexBreakdown } from './AgeSexBreakdown';
import { useNotificacoesBreakdown } from './useNotificacoes';
import { useVigilanciaFilterStore, VIGILANCIA_DEFAULT_STATE } from '../../store/vigilanciaFilterStore';
import type { BreakdownResponse } from '../../types/api';

const mockUseNotificacoesBreakdown = vi.mocked(useNotificacoesBreakdown);

function breakdownRow(overrides: Partial<BreakdownResponse>): BreakdownResponse {
  return {
    campo: 'faixa_etaria',
    categoria: '20-29',
    codigo: '20-29',
    total_notificacoes: 10,
    ...overrides,
  };
}

function stubHook(rows: BreakdownResponse[]) {
  mockUseNotificacoesBreakdown.mockReturnValue({
    rows,
    isLoading: false,
    isError: false,
    refetch: vi.fn(),
  });
}

describe('AgeSexBreakdown', () => {
  beforeEach(() => {
    useVigilanciaFilterStore.setState({ ...VIGILANCIA_DEFAULT_STATE });
    vi.clearAllMocks();
  });

  it('requests faixa_etaria and sexo when no agravo is selected', () => {
    useVigilanciaFilterStore.setState({ agravo: '' });
    stubHook([breakdownRow({})]);

    render(<AgeSexBreakdown />);

    const calledCampos = mockUseNotificacoesBreakdown.mock.calls.map((args) => args[0]);
    expect(calledCampos).toContain('faixa_etaria');
    expect(calledCampos).toContain('sexo');
  });

  it('requests faixa_etaria and sexo when a single agravo is selected', () => {
    useVigilanciaFilterStore.setState({ agravo: 'DENG' });
    stubHook([breakdownRow({})]);

    render(<AgeSexBreakdown />);

    const calledCampos = mockUseNotificacoesBreakdown.mock.calls.map((args) => args[0]);
    expect(calledCampos).toContain('faixa_etaria');
    expect(calledCampos).toContain('sexo');
  });

  it('renders both chart titles', () => {
    useVigilanciaFilterStore.setState({ agravo: '' });
    stubHook([breakdownRow({})]);

    render(<AgeSexBreakdown />);

    expect(screen.getByText('Notificações por faixa etária')).toBeTruthy();
    expect(screen.getByText('Notificações por sexo')).toBeTruthy();
  });

  it('has no "casos confirmados" text anywhere', () => {
    useVigilanciaFilterStore.setState({ agravo: '' });
    stubHook([breakdownRow({})]);

    render(<AgeSexBreakdown />);

    expect(screen.queryByText(/casos confirmados/)).toBeNull();
  });
});
