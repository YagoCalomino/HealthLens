/**
 * EpidemicCurve.test.tsx — pivot-function unit tests + rendering smoke tests.
 *
 * Mocks useNotificacoesCurva directly (avoids real network calls) and
 * ResponsiveContainer from recharts (jsdom has no layout engine/ResizeObserver).
 */
import React from 'react';
import { describe, it, expect, beforeEach, vi } from 'vitest';
import { render, screen } from '@testing-library/react';

vi.mock('./useNotificacoes', () => ({
  useNotificacoesCurva: vi.fn(),
}));

vi.mock('recharts', async () => {
  const actual = await vi.importActual<typeof import('recharts')>('recharts');
  return {
    ...actual,
    ResponsiveContainer: ({ children }: { children: React.ReactNode }) => (
      <div data-testid="responsive-container" style={{ width: 600, height: 260 }}>
        {children}
      </div>
    ),
  };
});

import { EpidemicCurve, buildCurvaChartData } from './EpidemicCurve';
import { useNotificacoesCurva } from './useNotificacoes';
import { useVigilanciaFilterStore, VIGILANCIA_DEFAULT_STATE } from '../../store/vigilanciaFilterStore';
import type { CurvaEpidemicaResponse } from '../../types/api';

const mockUseNotificacoesCurva = vi.mocked(useNotificacoesCurva);

function curvaRow(overrides: Partial<CurvaEpidemicaResponse>): CurvaEpidemicaResponse {
  return {
    ano_epidemiologico: 2023,
    semana_epidemiologica: 1,
    total_notificacoes: 10,
    taxa_por_100k: 1.2,
    ...overrides,
  };
}

describe('buildCurvaChartData', () => {
  it('produces exactly 53 rows keyed by semana 1..53 with both year keys', () => {
    const rows: CurvaEpidemicaResponse[] = [
      curvaRow({ ano_epidemiologico: 2023, semana_epidemiologica: 1, total_notificacoes: 5 }),
      curvaRow({ ano_epidemiologico: 2024, semana_epidemiologica: 1, total_notificacoes: 8 }),
    ];
    const result = buildCurvaChartData(rows);
    expect(result).toHaveLength(53);
    expect(result.map((r) => r.semana)).toEqual(Array.from({ length: 53 }, (_, i) => i + 1));
    expect(result[0]).toHaveProperty('2023');
    expect(result[0]).toHaveProperty('2024');
  });

  it('a missing week for one year yields null while an explicit zero yields 0', () => {
    const rows: CurvaEpidemicaResponse[] = [
      // 2023 has an explicit zero at week 2; 2024 has no row at all for week 2.
      curvaRow({ ano_epidemiologico: 2023, semana_epidemiologica: 1, total_notificacoes: 5 }),
      curvaRow({ ano_epidemiologico: 2023, semana_epidemiologica: 2, total_notificacoes: 0 }),
      curvaRow({ ano_epidemiologico: 2024, semana_epidemiologica: 1, total_notificacoes: 3 }),
    ];
    const result = buildCurvaChartData(rows);
    const week2 = result.find((r) => r.semana === 2)!;
    expect(week2['2023']).toBe(0);
    expect(week2['2024']).toBeNull();
  });
});

function Wrapper({ children }: { children: React.ReactNode }) {
  return <>{children}</>;
}

describe('EpidemicCurve', () => {
  beforeEach(() => {
    useVigilanciaFilterStore.setState({ ...VIGILANCIA_DEFAULT_STATE });
    vi.clearAllMocks();
  });

  it('renders "Nenhuma notificação encontrada" for an empty response', () => {
    mockUseNotificacoesCurva.mockReturnValue({
      rows: [],
      isLoading: false,
      isError: false,
      refetch: vi.fn(),
    });

    render(<EpidemicCurve />, { wrapper: Wrapper });

    expect(screen.getByText('Nenhuma notificação encontrada')).toBeTruthy();
  });

  it('renders "Não foi possível carregar os dados" for an errored query, not the raw error string', () => {
    mockUseNotificacoesCurva.mockReturnValue({
      rows: [],
      isLoading: false,
      isError: true,
      refetch: vi.fn(),
    });

    render(<EpidemicCurve />, { wrapper: Wrapper });

    expect(screen.getByText('Não foi possível carregar os dados')).toBeTruthy();
    expect(screen.queryByText(/Error:/)).toBeNull();
    expect(screen.queryByText(/TypeError/)).toBeNull();
  });

  it('renders the chart container (not the empty/error state) when data is present', () => {
    mockUseNotificacoesCurva.mockReturnValue({
      rows: [
        curvaRow({ ano_epidemiologico: 2023, semana_epidemiologica: 1, total_notificacoes: 5 }),
        curvaRow({ ano_epidemiologico: 2024, semana_epidemiologica: 1, total_notificacoes: 8 }),
      ],
      isLoading: false,
      isError: false,
      refetch: vi.fn(),
    });

    render(<EpidemicCurve />, { wrapper: Wrapper });

    expect(screen.getByTestId('responsive-container')).toBeTruthy();
    expect(screen.queryByText('Nenhuma notificação encontrada')).toBeNull();
    expect(screen.queryByText('Não foi possível carregar os dados')).toBeNull();
  });
});
