import React from 'react';
import {
  ComposedChart,
  Area,
  Line,
  ReferenceLine,
  XAxis,
  YAxis,
  Tooltip,
  ResponsiveContainer,
} from 'recharts';
import { useForecast } from './useForecast';
import { useHistoricalSeries } from './useHistoricalSeries';
import { buildChartData, hasForecast } from './buildChartData';
import { ChartTooltip } from '../../components/Tooltip';
import { LoadingState } from '../../components/LoadingState';
import { ErrorBoundary } from '../../components/ErrorBoundary';

// --- Empty state — no historical data ----------------------------------------

function EmptyHistorical(): React.ReactElement {
  return (
    <div
      style={{
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        height: 190,
        color: 'var(--text-secondary)',
        fontFamily: 'var(--font-ui)',
        fontSize: 'var(--text-base)',
      }}
    >
      Sem dados históricos para os filtros selecionados.
    </div>
  );
}

// --- Error state — inline fetch error ----------------------------------------

function FetchError({ onRetry }: { onRetry?: () => void }): React.ReactElement {
  return (
    <div
      style={{
        display: 'flex',
        flexDirection: 'column',
        alignItems: 'center',
        justifyContent: 'center',
        height: 320,
        gap: 'var(--space-2)',
        color: 'var(--text-secondary)',
        fontFamily: 'var(--font-ui)',
      }}
    >
      <p
        style={{
          fontSize: 'var(--text-md)',
          fontWeight: 'var(--weight-semibold)',
          color: 'var(--status-alert)',
          margin: 0,
        }}
      >
        Erro ao carregar previsão
      </p>
      <p
        style={{
          fontSize: 'var(--text-base)',
          color: 'var(--text-secondary)',
          margin: 0,
        }}
      >
        Não foi possível obter os dados de previsão. Tente novamente.
      </p>
      {onRetry && (
        <button
          onClick={onRetry}
          style={{
            fontFamily: 'var(--font-ui)',
            fontSize: 'var(--text-base)',
            fontWeight: 'var(--weight-semibold)',
            background: 'var(--accent)',
            color: '#ffffff',
            border: 'none',
            borderRadius: 'var(--radius-md)',
            padding: 'var(--space-2) var(--space-4)',
            cursor: 'pointer',
            marginTop: 'var(--space-2)',
          }}
        >
          Tentar novamente
        </button>
      )}
    </div>
  );
}

// --- Notice — forecast not available (historical only) -----------------------

function NoForecastNotice(): React.ReactElement {
  return (
    <div
      style={{
        display: 'flex',
        flexDirection: 'column',
        gap: 'var(--space-1)',
        padding: 'var(--space-2) var(--space-4)',
        background: 'var(--surface-control)',
        borderRadius: 'var(--radius-sm)',
        marginBottom: 'var(--space-4)',
        fontFamily: 'var(--font-ui)',
      }}
    >
      <p
        style={{
          fontSize: 'var(--text-base)',
          fontWeight: 'var(--weight-semibold)',
          color: 'var(--status-warning)',
          margin: 0,
        }}
      >
        Previsão não disponível
      </p>
      <p
        style={{
          fontSize: 'var(--text-base)',
          color: 'var(--text-secondary)',
          margin: 0,
        }}
      >
        Esta série não possui dados suficientes para previsão. O gráfico exibe apenas o histórico.
      </p>
    </div>
  );
}

// --- TimeSeriesChart ----------------------------------------------------------

/**
 * ComposedChart overlaying:
 * - CI 95% area band (bottom-most layer)
 * - CI 80% area band
 * - Historical taxa_por_100k line
 * - AutoARIMA forecast line
 * - Prophet forecast line (dashed)
 * - ReferenceLine at ano_referencia (forecast start divider)
 *
 * Performance: isAnimationActive=false + dot=false on all series.
 * XSS: All values rendered via JSX text interpolation and toLocaleString.
 * Tooltip is declared before any Legend (Recharts v3 z-index requirement).
 */
export function TimeSeriesChart(): React.ReactElement {
  const { data: resp, isLoading: fcLoading, isError: fcError, hasMunicipio } = useForecast();
  const { series, isLoading: histLoading, isError: histError } = useHistoricalSeries();

  // No municipio: show aggregated historical series from mv_taxa_uf_ano
  if (!hasMunicipio) {
    if (histLoading) return <LoadingState variant="skeleton-chart" label="Carregando série histórica..." />;
    if (histError) return <FetchError />;
    if (series.length === 0) return <EmptyHistorical />;
    return (
      <ErrorBoundary context="gráfico histórico">
        <div style={{ flex: 1, minHeight: 0 }}>
          <ResponsiveContainer width="100%" height="100%" debounce={50}>
            <ComposedChart data={series} margin={{ top: 8, right: 24, bottom: 0, left: 0 }}>
              <Line
                dataKey="taxa"
                stroke="var(--text-secondary)"
                strokeWidth={1.5}
                dot={false}
                isAnimationActive={false}
              />
              <XAxis
                dataKey="ano"
                type="number"
                domain={['dataMin', 'dataMax']}
                tickCount={8}
                tickFormatter={(v) => String(v)}
                tick={{ fontFamily: 'var(--font-mono)', fontSize: 10 }}
              />
              <YAxis
                tickFormatter={(v) => (v as number).toLocaleString('pt-BR')}
                tick={{ fontFamily: 'var(--font-mono)', fontSize: 10 }}
                unit="/100k"
                width={72}
              />
              <Tooltip cursor={{ strokeDasharray: '3 3' }} content={<ChartTooltip />} />
            </ComposedChart>
          </ResponsiveContainer>
        </div>
        <p
          style={{
            flexShrink: 0,
            textAlign: 'center',
            fontFamily: 'var(--font-ui)',
            fontSize: 'var(--text-xs)',
            color: 'var(--text-muted)',
            margin: '4px 0 0',
          }}
        >
          Clique em um município no mapa para ver previsões.
        </p>
      </ErrorBoundary>
    );
  }

  // Municipio selected: show forecast chart
  if (fcLoading) {
    return <LoadingState variant="skeleton-chart" label="Carregando previsões..." />;
  }

  if (fcError || !resp) {
    return <FetchError />;
  }

  const chartData = buildChartData(resp);
  const hasForecasts = hasForecast(resp);

  return (
    <ErrorBoundary context="gráfico">
      {!hasForecasts && <NoForecastNotice />}
      <div style={{ flex: 1, minHeight: 0 }}>
      <ResponsiveContainer width="100%" height="100%" debounce={50}>
        <ComposedChart data={chartData} margin={{ top: 8, right: 24, bottom: 0, left: 0 }}>
          {/* CI areas — bottom to top render order */}
          <Area
            dataKey={['ci95_inf', 'ci95_sup'] as unknown as string}
            fill="var(--forecast)"
            fillOpacity={0.08}
            strokeWidth={0}
            isAnimationActive={false}
          />
          <Area
            dataKey={['ci80_inf', 'ci80_sup'] as unknown as string}
            fill="var(--forecast)"
            fillOpacity={0.18}
            strokeWidth={0}
            isAnimationActive={false}
          />
          {/* Lines */}
          <Line
            dataKey="historico"
            stroke="var(--text-secondary)"
            strokeWidth={1.5}
            dot={false}
            isAnimationActive={false}
          />
          <Line
            dataKey="autoarima"
            stroke="var(--forecast)"
            strokeWidth={2}
            dot={false}
            isAnimationActive={false}
          />
          <Line
            dataKey="prophet"
            stroke="var(--accent-hover)"
            strokeWidth={1.5}
            strokeDasharray="4 2"
            dot={false}
            isAnimationActive={false}
          />
          {/* Reference line at ano_referencia — forecast start divider */}
          <ReferenceLine
            x={resp.ano_referencia}
            stroke="var(--forecast)"
            strokeDasharray="6 3"
            strokeOpacity={0.5}
          />
          <XAxis
            dataKey="ano"
            type="number"
            domain={['dataMin', 'dataMax']}
            tickCount={8}
            tickFormatter={(v) => String(v)}
            tick={{ fontFamily: 'var(--font-mono)', fontSize: 10 }}
          />
          <YAxis
            tickFormatter={(v) => (v as number).toLocaleString('pt-BR')}
            tick={{ fontFamily: 'var(--font-mono)', fontSize: 10 }}
            unit="/100k"
            width={72}
          />
          {/* Tooltip BEFORE Legend — required by Recharts v3 z-index (DOM render order) */}
          <Tooltip
            cursor={{ strokeDasharray: '3 3' }}
            content={<ChartTooltip />}
          />
        </ComposedChart>
      </ResponsiveContainer>
      </div>
    </ErrorBoundary>
  );
}
