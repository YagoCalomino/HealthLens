import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';
import { KpiStrip } from './KpiStrip';
import type { ForecastResponse, PrevisaoItem } from '../types/api';

function previsao(ano: number, valor_previsto: number): PrevisaoItem {
  return { ano, valor_previsto, ci80_inf: null, ci80_sup: null, ci95_inf: null, ci95_sup: null };
}

function forecastMG(previsoes: PrevisaoItem[]): ForecastResponse {
  return {
    municipio: { codigo_ibge_6: '310010', nome_municipio: 'Abadia dos Dourados', sigla_uf: 'MG' },
    metrica: 'taxa_mortalidade_100k',
    ano_referencia: 2024,
    historico: [],
    modelos: { Prophet: { mase: null, smape: null, previsoes } },
  };
}

describe('KpiStrip — state forecast card', () => {
  it('shows the value of the year in its label (first year after ano_referencia), not the last horizon year', () => {
    render(
      <KpiStrip
        rows={[]}
        forecasts={forecastMG([previsao(2025, 838.93), previsao(2026, 859.68), previsao(2027, 880.44)])}
        uf="MG"
        municipio=""
        anoInicio={2015}
        anoFim={2023}
        indicador="SIM"
        coberturaTotal={853}
      />
    );
    expect(screen.getByText('Previsão UF · MG · 2025')).toBeTruthy();
    expect(screen.getByText('839')).toBeTruthy();
    expect(screen.queryByText('880')).toBeNull();
  });

  it('skips forecast rows at or before ano_referencia', () => {
    render(
      <KpiStrip
        rows={[]}
        forecasts={forecastMG([previsao(2024, 800), previsao(2025, 838.93), previsao(2026, 859.68)])}
        uf="MG"
        municipio=""
        anoInicio={2015}
        anoFim={2023}
        indicador="SIM"
        coberturaTotal={853}
      />
    );
    expect(screen.getByText('Previsão UF · MG · 2025')).toBeTruthy();
    expect(screen.getByText('839')).toBeTruthy();
  });
});
