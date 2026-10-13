import React from 'react';

// ─── Types ───────────────────────────────────────────────────────────────────

interface PayloadEntry {
  name: string;
  value: number;
  color: string;
  dataKey: string;
}

interface ChartTooltipProps {
  active?: boolean;
  payload?: PayloadEntry[];
  label?: string | number;
}

export interface MapTooltipProps {
  nome: string;
  taxa: number | null;
  ano: number;
  x: number;
  y: number;
  visible: boolean;
}

// ─── Shared helpers ──────────────────────────────────────────────────────────

function formatPtBR(value: number): string {
  return value.toLocaleString('pt-BR', {
    minimumFractionDigits: 1,
    maximumFractionDigits: 1,
  });
}

const tooltipContainerStyle: React.CSSProperties = {
  background: 'var(--bg-base)',
  border: '1px solid var(--border-control)',
  borderRadius: 'var(--radius-sm)',
  padding: 'var(--space-2)',
  boxShadow: 'var(--shadow-elevated)',
  pointerEvents: 'none',
  zIndex: 'var(--z-tooltip)' as unknown as number,
  animation: 'tooltip-in 120ms ease-out',
};

// ─── ChartTooltip ─────────────────────────────────────────────────────────────
// Used as Recharts <Tooltip content={<ChartTooltip />} />

export function ChartTooltip({ active, payload, label }: ChartTooltipProps): React.ReactElement | null {
  if (!active || !payload?.length) return null;

  return (
    <div style={tooltipContainerStyle}>
      <p
        style={{
          fontFamily: 'var(--font-ui)',
          fontSize: 'var(--text-xs)',
          color: 'var(--text-primary)',
          margin: '0 0 4px 0',
        }}
      >
        Ano: {label}
      </p>
      {payload.map((entry, index) => (
        <p
          key={index}
          style={{
            fontFamily: 'var(--font-ui)',
            fontSize: 'var(--text-xs)',
            color: 'var(--text-secondary)',
            margin: '0 0 2px 0',
          }}
        >
          {entry.name}:{' '}
          <span
            style={{
              fontFamily: 'var(--font-mono)',
              color: 'var(--text-primary)',
            }}
          >
            {formatPtBR(entry.value)} / 100 mil hab.
          </span>
        </p>
      ))}
    </div>
  );
}

// ─── MapTooltip ───────────────────────────────────────────────────────────────
// Positioned map hover tooltip — rendered at mouse coordinates via CSS left/top

export function MapTooltip({ nome, taxa, ano, x, y, visible }: MapTooltipProps): React.ReactElement | null {
  if (!visible) return null;

  return (
    <div
      style={{
        ...tooltipContainerStyle,
        position: 'fixed',
        left: x,
        top: y,
      }}
    >
      <p
        style={{
          fontFamily: 'var(--font-ui)',
          fontSize: 'var(--text-xs)',
          fontWeight: 'var(--weight-semibold)',
          color: 'var(--text-primary)',
          margin: '0 0 4px 0',
        }}
      >
        {nome}
      </p>
      {taxa !== null ? (
        <>
          <p
            style={{
              fontFamily: 'var(--font-ui)',
              fontSize: 'var(--text-xs)',
              color: 'var(--text-secondary)',
              margin: '0 0 2px 0',
            }}
          >
            Taxa:{' '}
            <span style={{ fontFamily: 'var(--font-mono)', color: 'var(--text-primary)' }}>
              {formatPtBR(taxa)} / 100 mil hab.
            </span>
          </p>
          <p
            style={{
              fontFamily: 'var(--font-ui)',
              fontSize: 'var(--text-xs)',
              color: 'var(--text-secondary)',
              margin: '0',
            }}
          >
            Ano:{' '}
            <span style={{ fontFamily: 'var(--font-mono)', color: 'var(--text-primary)' }}>
              {ano}
            </span>
          </p>
        </>
      ) : (
        <p
          style={{
            fontFamily: 'var(--font-ui)',
            fontSize: 'var(--text-xs)',
            color: 'var(--text-secondary)',
            margin: '0',
          }}
        >
          Sem dados disponíveis
        </p>
      )}
    </div>
  );
}
