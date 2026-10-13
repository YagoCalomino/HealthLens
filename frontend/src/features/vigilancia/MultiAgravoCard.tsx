import React from 'react';
import { Line, LineChart, ResponsiveContainer, XAxis, YAxis } from 'recharts';
import { KpiCard } from '../../components/KpiCard';
import { LoadingState } from '../../components/LoadingState';
import { useVigilanciaFilterStore } from '../../store/vigilanciaFilterStore';
import { useMultiAgravoComparison } from './useNotificacoes';
import type { AgravoCodigo, NotificacaoSummaryResponse } from '../../types/api';

// Portuguese slot labels, in the fixed display order.
const AGRAVO_LABELS: Record<AgravoCodigo, string> = {
  DENG: 'Dengue',
  CHIK: 'Chikungunya',
  ANIM: 'Animais peçonhentos',
};

// Agravo identity colors — DENG mirrors --accent (#3F6FFF), ANIM mirrors
// --pos (#4FD1B0), CHIK reuses the existing CLUSTER_6[2] hex (#F0B35B). These
// three colors MUST stay consistent across every per-agravo surface.
const AGRAVO_COLORS: Record<AgravoCodigo, string> = {
  DENG: '#3F6FFF',
  CHIK: '#F0B35B',
  ANIM: '#4FD1B0',
};

const AGRAVO_ORDER: AgravoCodigo[] = ['DENG', 'CHIK', 'ANIM'];

interface AnoSeriesPoint {
  ano: number;
  total_notificacoes: number;
}

/** Aggregates (…, ano) rows down to one point per ano — SUM, mirroring the
 * backend's own SUM-based taxa_por_100k aggregation reasoning. */
function aggregateByAno(rows: NotificacaoSummaryResponse[]): AnoSeriesPoint[] {
  const byAno = new Map<number, number>();
  for (const row of rows) {
    byAno.set(row.ano, (byAno.get(row.ano) ?? 0) + row.total_notificacoes);
  }
  return Array.from(byAno.entries())
    .map(([ano, total_notificacoes]) => ({ ano, total_notificacoes }))
    .sort((a, b) => a.ano - b.ano);
}

/** Summed taxa_por_100k for the latest ano present in the filtered rows. */
function latestTaxa(rows: NotificacaoSummaryResponse[]): number | null {
  if (rows.length === 0) return null;
  const latestAno = Math.max(...rows.map((r) => r.ano));
  const latestRows = rows.filter((r) => r.ano === latestAno);
  return latestRows.reduce((sum, r) => sum + (r.taxa_por_100k ?? 0), 0);
}

const emptyStateTextStyle: React.CSSProperties = {
  fontFamily: 'var(--font-ui)',
  fontSize: 'var(--text-base)',
  color: 'var(--text-secondary)',
  margin: 0,
  textAlign: 'left',
};

function EmptySlot({ label }: { label: string }): React.ReactElement {
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--space-1)', minHeight: 90 }}>
      <p style={{ ...emptyStateTextStyle, fontWeight: 'var(--weight-semibold)', color: 'var(--text-primary)' }}>
        Nenhuma notificação encontrada
      </p>
      <p style={emptyStateTextStyle}>
        {`Não há notificações de ${label} para o período e localização selecionados. Ajuste os filtros ou tente outro agravo.`}
      </p>
    </div>
  );
}

function ErrorSlot(): React.ReactElement {
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--space-1)', minHeight: 90 }}>
      <p style={{ ...emptyStateTextStyle, fontWeight: 'var(--weight-semibold)', color: 'var(--status-alert)' }}>
        Não foi possível carregar os dados
      </p>
      <p style={emptyStateTextStyle}>
        Ocorreu um erro ao buscar notificações. Verifique sua conexão e tente novamente.
      </p>
    </div>
  );
}

interface AgravoSlotProps {
  agravo: AgravoCodigo;
  rows: NotificacaoSummaryResponse[];
  isLoading: boolean;
  isError: boolean;
}

const slotButtonStyle: React.CSSProperties = {
  flex: 1,
  minWidth: 0,
  display: 'flex',
  flexDirection: 'column',
  gap: 'var(--space-2)',
  background: 'var(--surface-card)',
  border: '1px solid var(--border-subtle)',
  borderRadius: 'var(--radius-lg)',
  padding: 'var(--space-4)',
  textAlign: 'left',
  cursor: 'pointer',
  font: 'inherit',
};

function AgravoSlot({ agravo, rows, isLoading, isError }: AgravoSlotProps): React.ReactElement {
  const label = AGRAVO_LABELS[agravo];
  const color = AGRAVO_COLORS[agravo];

  const handleClick = () => useVigilanciaFilterStore.getState().setAgravo(agravo);

  let body: React.ReactElement;
  if (isLoading) {
    body = <LoadingState variant="skeleton-chart" label={`Carregando notificações de ${label}...`} />;
  } else if (isError) {
    body = <ErrorSlot />;
  } else if (rows.length === 0) {
    // NOTE: with only ANIM/2023 rows currently loaded in the database,
    // the DENG and CHIK slots are expected to render
    // this empty state during real verification — this is a data-availability
    // condition, not a bug.
    body = <EmptySlot label={label} />;
  } else {
    const taxa = latestTaxa(rows);
    const series = aggregateByAno(rows);
    body = (
      <>
        <KpiCard label={label} value={taxa != null ? taxa.toFixed(1) : '—'} accentColor={color} />
        <div style={{ height: 90 }}>
          <ResponsiveContainer width="100%" height="100%" debounce={50}>
            <LineChart data={series} margin={{ top: 4, right: 4, bottom: 0, left: 0 }}>
              <Line
                type="monotone"
                dataKey="total_notificacoes"
                stroke={color}
                strokeWidth={2}
                dot={false}
                isAnimationActive={false}
              />
              <XAxis dataKey="ano" hide />
              <YAxis hide />
            </LineChart>
          </ResponsiveContainer>
        </div>
      </>
    );
  }

  return (
    <button type="button" onClick={handleClick} aria-label={label} style={slotButtonStyle}>
      {body}
    </button>
  );
}

const rowStyle: React.CSSProperties = {
  display: 'flex',
  flexWrap: 'wrap',
  gap: 'var(--space-4)',
};

/**
 * Multi-agravo comparison card — the panel's default view. Three
 * equal-width slots (Dengue, Chikungunya, Animais peçonhentos), each backed by
 * one of useMultiAgravoComparison's three parallel single-agravo requests.
 * Clicking a slot narrows the panel to that agravo.
 */
export function MultiAgravoCard(): React.ReactElement {
  const slots = useMultiAgravoComparison();
  const byAgravo = new Map(slots.map((slot) => [slot.agravo, slot]));

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--space-3)' }}>
      <div>
        <p style={{ fontFamily: 'var(--font-ui)', fontSize: 'var(--text-xs)', color: 'var(--text-muted)', margin: '4px 0 0 0' }}>
          Taxa de notificação por 100 mil habitantes no último ano com dados disponíveis. Clique em um agravo para filtrar o painel.
        </p>
      </div>
      <div style={rowStyle}>
        {AGRAVO_ORDER.map((agravo) => {
          const slot = byAgravo.get(agravo);
          return (
            <AgravoSlot
              key={agravo}
              agravo={agravo}
              rows={slot?.rows ?? []}
              isLoading={slot?.isLoading ?? false}
              isError={slot?.isError ?? false}
            />
          );
        })}
      </div>
    </div>
  );
}
