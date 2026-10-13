import React from 'react';
import {
  ScatterChart,
  Scatter,
  XAxis,
  YAxis,
  Cell,
  Tooltip,
  ResponsiveContainer,
} from 'recharts';
import { ErrorBoundary } from '../../components/ErrorBoundary';
import { LoadingState } from '../../components/LoadingState';
import { useFilterStore } from '../../store/filterStore';
import { useClusters, type ClusterPoint } from './useClusters';
import { CLUSTER_6 } from '../../lib/choropleth';

// Custom tooltip for cluster scatter points
interface TooltipPayloadItem {
  payload: ClusterPoint;
}

interface ClusterTooltipProps {
  active?: boolean;
  payload?: TooltipPayloadItem[];
}

function ClusterTooltip({ active, payload }: ClusterTooltipProps): React.ReactElement | null {
  if (!active || !payload || payload.length === 0) return null;
  const point = payload[0].payload;
  return (
    <div
      style={{
        fontFamily: 'var(--font-mono)',
        fontSize: 'var(--text-xs)',
        background: 'var(--bg-base)',
        border: '1px solid var(--border-control)',
        borderRadius: 'var(--radius-sm)',
        padding: 'var(--space-2)',
        boxShadow: 'var(--shadow-elevated)',
        pointerEvents: 'none',
      }}
    >
      <div style={{ fontFamily: 'var(--font-ui)', fontWeight: 'var(--weight-semibold)', color: 'var(--text-primary)', marginBottom: 4 }}>
        {point.label}
      </div>
      <div style={{ color: 'var(--text-secondary)' }}>
        {point.cluster_nome ?? `Cluster ${point.cluster_id}`}
      </div>
      <div style={{ color: 'var(--text-secondary)', marginTop: 2 }}>
        PCA 1: {point.pca_x?.toFixed(3)}
      </div>
      <div style={{ color: 'var(--text-secondary)' }}>
        PCA 2: {point.pca_y?.toFixed(3)}
      </div>
    </div>
  );
}

function ClusterScatterPlotInner(): React.ReactElement {
  const { points, level, isLoading, isFetchingNextPage, total, isError } = useClusters();
  const setMunicipio = useFilterStore((s) => s.setMunicipio);
  const setUf = useFilterStore((s) => s.setUf);
  const handleSelect = (point: ClusterPoint) => (level === 'national' ? setUf(point.key) : setMunicipio(point.key));

  if (isError) {
    // Render error text — ErrorBoundary wraps the outer component for thrown errors;
    // API errors surfaced via isError use inline fallback to avoid requiring a thrown error
    return (
      <div style={{ color: 'var(--status-alert)', fontFamily: 'var(--font-ui)', fontSize: 'var(--text-base)' }}>
        Erro ao carregar agrupamentos
      </div>
    );
  }

  const loadingLabel = level === 'national' ? 'Carregando estados...' : 'Carregando municípios...';

  if (isLoading) {
    return (
      <div>
        <p style={{ fontFamily: 'var(--font-ui)', fontSize: 'var(--text-base)', color: 'var(--text-primary)', margin: '0 0 var(--space-2) 0' }}>
          {loadingLabel}
        </p>
        <LoadingState variant="spinner" label={loadingLabel} />
      </div>
    );
  }

  // While fetching subsequent pages, show a spinner overlay with total count
  const fetchingMoreContent = isFetchingNextPage ? (
    <div style={{ display: 'flex', alignItems: 'center', gap: 'var(--space-2)', marginBottom: 'var(--space-2)' }}>
      <LoadingState variant="spinner" label={`Carregando municípios... ${total} carregados`} />
      <span style={{ fontFamily: 'var(--font-ui)', fontSize: 'var(--text-base)', color: 'var(--text-secondary)' }}>
        Aguarde enquanto carregamos os {total} municípios.
      </span>
    </div>
  ) : null;

  return (
    <div style={{ flex: 1, minHeight: 0 }}>
      {fetchingMoreContent}
      <ResponsiveContainer width="100%" height="100%" debounce={50}>
        <ScatterChart>
          <XAxis
            dataKey="pca_x"
            type="number"
            name="PCA 1"
            tick={{ fontFamily: 'var(--font-mono)', fontSize: 10 }}
          />
          <YAxis
            dataKey="pca_y"
            type="number"
            name="PCA 2"
            tick={{ fontFamily: 'var(--font-mono)', fontSize: 10 }}
          />
          <Tooltip content={<ClusterTooltip />} />
          <Scatter
            data={points}
            name={level === 'national' ? 'Estados' : 'Municípios'}
            // Dot radius: 4px default, 6px on active (hover)
            shape={(props: React.SVGProps<SVGCircleElement> & { cx?: number; cy?: number; payload?: ClusterPoint }) => {
              const { cx, cy, payload } = props;
              if (cx === undefined || cy === undefined || !payload) return <></>;
              const fill = CLUSTER_6[payload.cluster_id] ?? CLUSTER_6[5];
              return (
                <circle
                  cx={cx}
                  cy={cy}
                  r={4}
                  fill={fill}
                  fillOpacity={0.8}
                  stroke={fill}
                  strokeWidth={0.5}
                  style={{ cursor: 'pointer' }}
                  onClick={() => handleSelect(payload)}
                />
              );
            }}
            activeShape={(props: React.SVGProps<SVGCircleElement> & { cx?: number; cy?: number; payload?: ClusterPoint }) => {
              const { cx, cy, payload } = props;
              if (cx === undefined || cy === undefined || !payload) return <></>;
              const fill = CLUSTER_6[payload.cluster_id] ?? CLUSTER_6[5];
              return (
                <circle
                  cx={cx}
                  cy={cy}
                  r={6}
                  fill={fill}
                  fillOpacity={1}
                  stroke={fill}
                  strokeWidth={1}
                  style={{ cursor: 'pointer' }}
                  onClick={() => handleSelect(payload)}
                />
              );
            }}
            onClick={(point) => {
              const p = point as unknown as ClusterPoint | null;
              if (p?.key) {
                handleSelect(p);
              }
            }}
          >
            {points.map((point, idx) => (
              <Cell
                key={`cell-${idx}`}
                fill={CLUSTER_6[point.cluster_id] ?? CLUSTER_6[5]}
              />
            ))}
          </Scatter>
        </ScatterChart>
      </ResponsiveContainer>
    </div>
  );
}

export function ClusterScatterPlot(): React.ReactElement {
  const uf = useFilterStore((s) => s.uf);
  return (
    <section style={{
      padding: 'var(--space-4)',
      background: 'var(--surface-card)',
      borderRadius: 'var(--radius-md)',
      height: '100%',
      boxSizing: 'border-box',
      display: 'flex',
      flexDirection: 'column',
    }}>
      <h2 style={{
        fontFamily: 'var(--font-ui)',
        fontSize: 'var(--text-md)',
        fontWeight: 'var(--weight-semibold)',
        color: 'var(--text-primary)',
        marginTop: 0,
        marginBottom: 'var(--space-4)',
        flexShrink: 0,
      }}>
        {uf ? 'Agrupamento de Municípios' : 'Agrupamento por Estado'}
      </h2>
      <ErrorBoundary
        context="agrupamentos"
        fallbackTitle="Erro ao carregar agrupamentos"
      >
        <ClusterScatterPlotInner />
      </ErrorBoundary>
    </section>
  );
}
