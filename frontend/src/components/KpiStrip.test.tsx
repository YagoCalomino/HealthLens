import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';
import { KpiStrip } from './KpiStrip';
import type { ForecastResponse, IndicadorResponse, PrevisaoItem } from '../types/api';

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

function ufRow(sigla_uf: string, ano: number, total_eventos: number, populacao: number): IndicadorResponse {
  return {
    sigla_uf, codigo_ibge: null, nome_municipio: null, ano, total_eventos, populacao,
    taxa_por_100k: (total_eventos / populacao) * 100000, fonte: 'SIM',
  };
}

// National 2015: 300 / 200.000 = 150/100k. 2023: 309 / 200.000 = 154,5/100k → +3,0%.
// A small UF (AC) sorts first and a different UF (TO) last, with rates 100 → 200:
// comparing those two rows (the old bug) gives +100%.
const NATIONAL_ROWS: IndicadorResponse[] = [
  ufRow('AC', 2015, 100, 100_000),
  ufRow('SP', 2015, 200, 100_000),
  ufRow('SP', 2023, 109, 100_000),
  ufRow('TO', 2023, 200, 100_000),
];

function renderNational(rows: IndicadorResponse[]) {
  render(
    <KpiStrip
      rows={rows}
      forecasts={null}
      uf=""
      municipio=""
      anoInicio={2015}
      anoFim={2023}
      indicador="SIM"
      coberturaTotal={27}
    />
  );
}

describe('KpiStrip — national view', () => {
  it('sums total_eventos over the whole selected period, not just the latest year', () => {
    renderNational(NATIONAL_ROWS);
    expect(screen.getByText('Total de óbitos · 2015–2023')).toBeTruthy();
    expect(screen.getByText('609')).toBeTruthy();
  });

  it('computes Variação from the national rate (Σ eventos / Σ população) of the first and last years', () => {
    renderNational(NATIONAL_ROWS);
    expect(screen.getByText('+3.0%')).toBeTruthy();
    expect(screen.queryByText('+100.0%')).toBeNull();
  });
});
