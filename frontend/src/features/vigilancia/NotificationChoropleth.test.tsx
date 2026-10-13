/**
 * NotificationChoropleth.test.tsx — drill-down state machine + collapse-to-latest-ano
 * pivot tests.
 *
 * Mocks react-simple-maps (jsdom has no SVG projection engine) and the
 * useNotificacoes summary hooks directly (avoids real network calls).
 */
import React from 'react';
import { describe, it, expect, beforeEach, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

const FAKE_NATIONAL_GEOS = [
  { rsmKey: 'geo-sp', id: 'SP', properties: { sigla: 'SP', name: 'São Paulo', codigo_ibg: '35' } },
  { rsmKey: 'geo-rj', id: 'RJ', properties: { sigla: 'RJ', name: 'Rio de Janeiro', codigo_ibg: '33' } },
];

vi.mock('react-simple-maps', () => ({
  ComposableMap: ({ children }: { children: React.ReactNode }) => (
    <div data-testid="composable-map">{children}</div>
  ),
  ZoomableGroup: ({ children }: { children: React.ReactNode }) => <>{children}</>,
  Geographies: ({
    geography,
    children,
  }: {
    geography: string;
    children: (arg: { geographies: typeof FAKE_NATIONAL_GEOS }) => React.ReactNode;
  }) => (
    <div data-testid="geographies" data-url={geography}>
      {children({ geographies: FAKE_NATIONAL_GEOS })}
    </div>
  ),
  Geography: ({
    className,
    onClick,
    'aria-label': ariaLabel,
    geography: _geography,
    ...rest
  }: {
    className?: string;
    onClick?: () => void;
    'aria-label'?: string;
    geography?: unknown;
    [key: string]: unknown;
  }) => (
    <path
      className={className}
      aria-label={ariaLabel}
      onClick={onClick}
      data-testid="geography"
      {...(rest as object)}
    />
  ),
}));

vi.mock('./useNotificacoes', () => ({
  useNotificacoesUfSummary: vi.fn(),
  useNotificacoesMunicipioSummary: vi.fn(),
}));

import { NotificationChoropleth, collapseToLatestAno } from './NotificationChoropleth';
import { useNotificacoesMunicipioSummary, useNotificacoesUfSummary } from './useNotificacoes';
import { useVigilanciaFilterStore, VIGILANCIA_DEFAULT_STATE } from '../../store/vigilanciaFilterStore';
import type { NotificacaoSummaryResponse } from '../../types/api';

const mockUfSummary = vi.mocked(useNotificacoesUfSummary);
const mockMunicipioSummary = vi.mocked(useNotificacoesMunicipioSummary);

function summaryRow(overrides: Partial<NotificacaoSummaryResponse>): NotificacaoSummaryResponse {
  return {
    sigla_uf: 'SP',
    codigo_ibge: null,
    nome_municipio: null,
    ano: 2023,
    agravo: 'ANIM',
    total_notificacoes: 100,
    taxa_por_100k: 12.5,
    ...overrides,
  };
}

describe('collapseToLatestAno', () => {
  it('collapses multi-ano rows to only the latest ano, dropping earlier years', () => {
    const rows: NotificacaoSummaryResponse[] = [
      summaryRow({ sigla_uf: 'SP', ano: 2022, taxa_por_100k: 5 }),
      summaryRow({ sigla_uf: 'SP', ano: 2023, taxa_por_100k: 12.5 }),
      summaryRow({ sigla_uf: 'RJ', ano: 2023, taxa_por_100k: 8 }),
    ];
    const { byCode, latestAno } = collapseToLatestAno(rows);
    expect(latestAno).toBe(2023);
    expect(byCode.size).toBe(2);
    expect(byCode.get('SP')?.taxa_por_100k).toBe(12.5);
    expect(byCode.get('RJ')?.taxa_por_100k).toBe(8);
  });

  it('returns an empty map and null latestAno for an empty rows array', () => {
    const { byCode, latestAno } = collapseToLatestAno([]);
    expect(byCode.size).toBe(0);
    expect(latestAno).toBeNull();
  });
});

describe('NotificationChoropleth', () => {
  beforeEach(() => {
    useVigilanciaFilterStore.setState({ ...VIGILANCIA_DEFAULT_STATE });
    vi.clearAllMocks();
    mockUfSummary.mockReturnValue({
      rows: [summaryRow({ sigla_uf: 'SP', ano: 2023, taxa_por_100k: 12.5 })],
      byCode: new Map(),
      isLoading: false,
      isError: false,
      refetch: vi.fn(),
    });
    mockMunicipioSummary.mockReturnValue({
      rows: [summaryRow({ sigla_uf: 'SP', codigo_ibge: '3550308', ano: 2023, taxa_por_100k: 20 })],
      byCode: new Map(),
      isLoading: false,
      isError: false,
      refetch: vi.fn(),
    });
  });

  it('requests the 27-UF TopoJSON URL when uf is empty (national level)', () => {
    render(<NotificationChoropleth />);
    expect(screen.getByTestId('geographies').getAttribute('data-url')).toBe('/topojson/br-ufs.json');
  });

  it('clicking a UF polygon sets store uf and switches to the municipal TopoJSON URL', async () => {
    const user = userEvent.setup();
    render(<NotificationChoropleth />);

    const paths = screen.getAllByTestId('geography');
    await user.click(paths[0]); // FAKE_NATIONAL_GEOS[0] → SP

    expect(useVigilanciaFilterStore.getState().uf).toBe('SP');
    expect(screen.getByTestId('geographies').getAttribute('data-url')).toBe('/topojson/uf/SP.json');
  });

  it('breadcrumb "Brasil" click resets uf to empty string', async () => {
    useVigilanciaFilterStore.setState({ uf: 'SP' });
    const user = userEvent.setup();
    render(<NotificationChoropleth />);

    await user.click(screen.getByRole('button', { name: 'Voltar para visão nacional' }));

    expect(useVigilanciaFilterStore.getState().uf).toBe('');
  });

  it('renders "Nenhuma notificação encontrada" when the active summary has no rows', () => {
    mockUfSummary.mockReturnValue({
      rows: [],
      byCode: new Map(),
      isLoading: false,
      isError: false,
      refetch: vi.fn(),
    });
    render(<NotificationChoropleth />);
    expect(screen.getByText('Nenhuma notificação encontrada')).toBeTruthy();
  });

  it('renders "Não foi possível carregar os dados" on an errored query, not the raw error string', () => {
    mockUfSummary.mockReturnValue({
      rows: [],
      byCode: new Map(),
      isLoading: false,
      isError: true,
      refetch: vi.fn(),
    });
    render(<NotificationChoropleth />);
    expect(screen.getByText('Não foi possível carregar os dados')).toBeTruthy();
    expect(screen.queryByText(/Error:/)).toBeNull();
  });
});
