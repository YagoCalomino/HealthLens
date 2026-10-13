/**
 * SeverityBreakdown.test.tsx — agravo-aware campo-selection tests + rendering
 * smoke tests.
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

import { SeverityBreakdown } from './SeverityBreakdown';
import { useNotificacoesBreakdown } from './useNotificacoes';
import { useVigilanciaFilterStore, VIGILANCIA_DEFAULT_STATE } from '../../store/vigilanciaFilterStore';
import type { BreakdownResponse } from '../../types/api';

const mockUseNotificacoesBreakdown = vi.mocked(useNotificacoesBreakdown);

function breakdownRow(overrides: Partial<BreakdownResponse>): BreakdownResponse {
  return {
    campo: 'gravidade',
    categoria: 'Grave',
    codigo: null,
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

describe('SeverityBreakdown', () => {
  beforeEach(() => {
    useVigilanciaFilterStore.setState({ ...VIGILANCIA_DEFAULT_STATE });
    vi.clearAllMocks();
  });

  it('renders nothing and issues zero fetch calls when agravo is empty', () => {
    useVigilanciaFilterStore.setState({ agravo: '' });

    const { container } = render(<SeverityBreakdown />);

    expect(container.firstChild).toBeNull();
    expect(mockUseNotificacoesBreakdown).not.toHaveBeenCalled();
  });

  it('requests gravidade and classi_fin for DENG, never tra_classi or tp_acidente', () => {
    useVigilanciaFilterStore.setState({ agravo: 'DENG' });
    stubHook([breakdownRow({})]);

    render(<SeverityBreakdown />);

    const calledCampos = mockUseNotificacoesBreakdown.mock.calls.map((args) => args[0]);
    expect(calledCampos).toContain('gravidade');
    expect(calledCampos).toContain('classi_fin');
    expect(calledCampos).not.toContain('tra_classi');
    expect(calledCampos).not.toContain('tp_acidente');
  });

  it('requests gravidade and classi_fin for CHIK, never tra_classi or tp_acidente', () => {
    useVigilanciaFilterStore.setState({ agravo: 'CHIK' });
    stubHook([breakdownRow({})]);

    render(<SeverityBreakdown />);

    const calledCampos = mockUseNotificacoesBreakdown.mock.calls.map((args) => args[0]);
    expect(calledCampos).toContain('gravidade');
    expect(calledCampos).toContain('classi_fin');
    expect(calledCampos).not.toContain('tra_classi');
    expect(calledCampos).not.toContain('tp_acidente');
  });

  it('requests tra_classi and tp_acidente for ANIM, never gravidade or classi_fin', () => {
    useVigilanciaFilterStore.setState({ agravo: 'ANIM' });
    stubHook([breakdownRow({ campo: 'tra_classi', categoria: 'Peçonhento' })]);

    render(<SeverityBreakdown />);

    const calledCampos = mockUseNotificacoesBreakdown.mock.calls.map((args) => args[0]);
    expect(calledCampos).toContain('tra_classi');
    expect(calledCampos).toContain('tp_acidente');
    expect(calledCampos).not.toContain('gravidade');
    expect(calledCampos).not.toContain('classi_fin');
  });

  it('renders an Ignorado category row returned by the API, not filtered out', () => {
    useVigilanciaFilterStore.setState({ agravo: 'DENG' });
    stubHook([
      breakdownRow({ categoria: 'Grave', total_notificacoes: 5 }),
      breakdownRow({ categoria: 'Ignorado', total_notificacoes: 2 }),
    ]);

    render(<SeverityBreakdown />);

    expect(screen.getAllByText(/Ignorado/).length).toBeGreaterThan(0);
  });

  it('shows the disclaimer sentence "não equivalem a casos confirmados"', () => {
    useVigilanciaFilterStore.setState({ agravo: 'DENG' });
    stubHook([breakdownRow({})]);

    render(<SeverityBreakdown />);

    expect(screen.getByText(/não equivalem a casos confirmados/)).toBeTruthy();
  });

  it('renders chart titles for DENG: gravidade and classificação final', () => {
    useVigilanciaFilterStore.setState({ agravo: 'DENG' });
    stubHook([breakdownRow({})]);

    render(<SeverityBreakdown />);

    expect(screen.getByText('Notificações por gravidade')).toBeTruthy();
    expect(screen.getByText('Notificações por classificação final')).toBeTruthy();
  });

  it('renders chart titles for ANIM: classificação do acidente and tipo de animal', () => {
    useVigilanciaFilterStore.setState({ agravo: 'ANIM' });
    stubHook([breakdownRow({ campo: 'tra_classi', categoria: 'Peçonhento' })]);

    render(<SeverityBreakdown />);

    expect(screen.getByText('Notificações por classificação do acidente')).toBeTruthy();
    expect(screen.getByText('Notificações por tipo de animal')).toBeTruthy();
  });
});
