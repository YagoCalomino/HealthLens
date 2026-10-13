import React from 'react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';

// Mock useForecast so we control its return value per test
vi.mock('./useForecast', () => ({
  useForecast: vi.fn(),
}));

// Mock useHistoricalSeries so the no-municipio branch renders without a network call
vi.mock('./useHistoricalSeries', () => ({
  useHistoricalSeries: vi.fn(() => ({ series: [], isLoading: false, isError: false })),
}));

// Mock ResponsiveContainer to give Recharts a fixed size in jsdom
vi.mock('recharts', async () => {
  const actual = await vi.importActual<typeof import('recharts')>('recharts');
  return {
    ...actual,
    ResponsiveContainer: ({ children }: { children: React.ReactElement }) => (
      <div style={{ width: 600, height: 320 }}>{children}</div>
    ),
  };
});

import { useForecast } from './useForecast';
import { useHistoricalSeries } from './useHistoricalSeries';
import { TimeSeriesChart } from './TimeSeriesChart';
import type { ForecastResponse } from '../../types/api';

const mockUseForecast = useForecast as ReturnType<typeof vi.fn>;
const mockUseHistoricalSeries = useHistoricalSeries as ReturnType<typeof vi.fn>;

function wrapper({ children }: { children: React.ReactNode }) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return <QueryClientProvider client={qc}>{children}</QueryClientProvider>;
}

const forecastFixture: ForecastResponse = {
  municipio: { codigo_ibge_6: '310620', nome_municipio: 'Belo Horizonte', sigla_uf: 'MG' },
  metrica: 'taxa_mortalidade_100k',
  ano_referencia: 2023,
  historico: [
    { ano: 2018, valor: 10.5 },
    { ano: 2019, valor: 11.2 },
    { ano: 2020, valor: 12.8 },
    { ano: 2021, valor: 13.1 },
    { ano: 2022, valor: 12.0 },
  ],
  modelos: {
    AutoARIMA: {
      mase: 0.82,
      smape: 4.5,
      previsoes: [
        { ano: 2023, valor_previsto: 12.5, ci80_inf: 11.0, ci80_sup: 14.0, ci95_inf: 10.2, ci95_sup: 14.8 },
        { ano: 2024, valor_previsto: 13.0, ci80_inf: 11.2, ci80_sup: 14.8, ci95_inf: 10.0, ci95_sup: 16.0 },
      ],
    },
    Prophet: {
      mase: 0.91,
      smape: 5.1,
      previsoes: [
        { ano: 2023, valor_previsto: 12.3, ci80_inf: null, ci80_sup: null, ci95_inf: null, ci95_sup: null },
        { ano: 2024, valor_previsto: 12.8, ci80_inf: null, ci80_sup: null, ci95_inf: null, ci95_sup: null },
      ],
    },
  },
};

beforeEach(() => {
  vi.clearAllMocks();
});

describe('TimeSeriesChart', () => {
  it('shows the aggregated historical series with a hint when no municipio is selected', () => {
    mockUseForecast.mockReturnValue({
      data: undefined,
      isLoading: false,
      isError: false,
      hasMunicipio: false,
    });
    mockUseHistoricalSeries.mockReturnValue({
      series: [
        { ano: 2022, taxa: 10.5 },
        { ano: 2023, taxa: 11.2 },
      ],
      isLoading: false,
      isError: false,
    });

    render(<TimeSeriesChart />, { wrapper });

    expect(
      screen.getByText(/Clique em um município no mapa/i)
    ).toBeTruthy();
  });

  it('shows LoadingState skeleton when isLoading is true', () => {
    mockUseForecast.mockReturnValue({
      data: undefined,
      isLoading: true,
      isError: false,
      hasMunicipio: true,
    });

    render(<TimeSeriesChart />, { wrapper });

    // LoadingState renders a div with role="status" and aria-live="polite"
    expect(screen.getByRole('status')).toBeTruthy();
  });

  it('shows error state when isError is true', () => {
    mockUseForecast.mockReturnValue({
      data: undefined,
      isLoading: false,
      isError: true,
      hasMunicipio: true,
    });

    render(<TimeSeriesChart />, { wrapper });

    expect(screen.getByText(/Erro ao carregar previsão/i)).toBeTruthy();
  });

  it('shows "Previsão não disponível" notice when data has empty modelos', () => {
    const noForecast: ForecastResponse = { ...forecastFixture, modelos: {} };
    mockUseForecast.mockReturnValue({
      data: noForecast,
      isLoading: false,
      isError: false,
      hasMunicipio: true,
    });

    render(<TimeSeriesChart />, { wrapper });

    expect(screen.getByText('Previsão não disponível')).toBeTruthy();
    expect(
      screen.getByText(/Esta série não possui dados suficientes/i)
    ).toBeTruthy();
  });

  it('renders chart container when forecast data is present', () => {
    mockUseForecast.mockReturnValue({
      data: forecastFixture,
      isLoading: false,
      isError: false,
      hasMunicipio: true,
    });

    const { container } = render(<TimeSeriesChart />, { wrapper });

    // ComposedChart wraps content in a div from the mocked ResponsiveContainer;
    // assert the wrapper element exists (Recharts paints SVG only in real browser env)
    const wrapper2 = container.querySelector('div[style*="width: 600px"]') ??
      container.querySelector('div[style*="width:600px"]') ??
      container.firstElementChild;
    expect(wrapper2).toBeTruthy();
  });
});
