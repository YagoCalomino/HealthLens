import { describe, it, expect } from 'vitest';
import { buildChartData, hasForecast } from './buildChartData';
import type { ForecastResponse } from '../../types/api';

// Fixture: histórico 2018-2022, AutoARIMA + Prophet 2023-2025, ano_referencia 2023
const fixture: ForecastResponse = {
  municipio: {
    codigo_ibge_6: '310620',
    nome_municipio: 'Belo Horizonte',
    sigla_uf: 'MG',
  },
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
        { ano: 2025, valor_previsto: 13.5, ci80_inf: 11.5, ci80_sup: 15.5, ci95_inf: 9.8, ci95_sup: 17.2 },
      ],
    },
    Prophet: {
      mase: 0.91,
      smape: 5.1,
      previsoes: [
        { ano: 2023, valor_previsto: 12.3, ci80_inf: null, ci80_sup: null, ci95_inf: null, ci95_sup: null },
        { ano: 2024, valor_previsto: 12.8, ci80_inf: null, ci80_sup: null, ci95_inf: null, ci95_sup: null },
        { ano: 2025, valor_previsto: 13.2, ci80_inf: null, ci80_sup: null, ci95_inf: null, ci95_sup: null },
      ],
    },
  },
};

describe('buildChartData', () => {
  it('returns one ChartDataPoint per unique ano, sorted ascending', () => {
    const result = buildChartData(fixture);
    const anos = result.map((p) => p.ano);
    // anos 2018–2025 = 8 points (2023 appears once)
    expect(anos).toEqual([2018, 2019, 2020, 2021, 2022, 2023, 2024, 2025]);
  });

  it('historical years carry historico value', () => {
    const result = buildChartData(fixture);
    const p2018 = result.find((p) => p.ano === 2018)!;
    expect(p2018.historico).toBe(10.5);
    expect(p2018.autoarima).toBeUndefined();
    expect(p2018.prophet).toBeUndefined();
  });

  it('forecast years carry autoarima and prophet values', () => {
    const result = buildChartData(fixture);
    const p2024 = result.find((p) => p.ano === 2024)!;
    expect(p2024.autoarima).toBe(13.0);
    expect(p2024.prophet).toBe(12.8);
    expect(p2024.historico).toBeUndefined();
  });

  it('ano_referencia (2023) appears once — no duplicate', () => {
    const result = buildChartData(fixture);
    const count2023 = result.filter((p) => p.ano === 2023).length;
    expect(count2023).toBe(1);
  });

  it('ci80/ci95 bounds come from AutoARIMA previsoes', () => {
    const result = buildChartData(fixture);
    const p2023 = result.find((p) => p.ano === 2023)!;
    expect(p2023.ci80_inf).toBe(11.0);
    expect(p2023.ci80_sup).toBe(14.0);
    expect(p2023.ci95_inf).toBe(10.2);
    expect(p2023.ci95_sup).toBe(14.8);
  });

  it('missing CI values are left undefined, not 0', () => {
    const fixtureNoCi: ForecastResponse = {
      ...fixture,
      modelos: {
        AutoARIMA: {
          mase: null,
          smape: null,
          previsoes: [
            { ano: 2023, valor_previsto: 12.5, ci80_inf: null, ci80_sup: null, ci95_inf: null, ci95_sup: null },
          ],
        },
      },
    };
    const result = buildChartData(fixtureNoCi);
    const p2023 = result.find((p) => p.ano === 2023)!;
    expect(p2023.ci80_inf).toBeUndefined();
    expect(p2023.ci80_sup).toBeUndefined();
    expect(p2023.ci95_inf).toBeUndefined();
    expect(p2023.ci95_sup).toBeUndefined();
  });

  it('when modelos has no Prophet key, prophet is undefined on every point', () => {
    const fixtureNoP: ForecastResponse = {
      ...fixture,
      modelos: {
        AutoARIMA: fixture.modelos['AutoARIMA'],
      },
    };
    const result = buildChartData(fixtureNoP);
    result.forEach((p) => {
      expect(p.prophet).toBeUndefined();
    });
  });

  it('when modelos is empty, result contains only historical points', () => {
    const fixtureNoForecast: ForecastResponse = {
      ...fixture,
      modelos: {},
    };
    const result = buildChartData(fixtureNoForecast);
    expect(result).toHaveLength(5); // only 2018-2022
    result.forEach((p) => {
      expect(p.autoarima).toBeUndefined();
      expect(p.prophet).toBeUndefined();
    });
  });
});

describe('hasForecast', () => {
  it('returns true when modelos has models with previsoes', () => {
    expect(hasForecast(fixture)).toBe(true);
  });

  it('returns false when modelos is empty', () => {
    const f: ForecastResponse = { ...fixture, modelos: {} };
    expect(hasForecast(f)).toBe(false);
  });

  it('returns false when all models have empty previsoes arrays', () => {
    const f: ForecastResponse = {
      ...fixture,
      modelos: {
        AutoARIMA: { mase: null, smape: null, previsoes: [] },
      },
    };
    expect(hasForecast(f)).toBe(false);
  });
});
