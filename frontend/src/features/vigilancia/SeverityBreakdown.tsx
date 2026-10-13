import React from 'react';
import { Bar, BarChart, Cell, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts';
import { LoadingState } from '../../components/LoadingState';
import { useVigilanciaFilterStore } from '../../store/vigilanciaFilterStore';
import { useNotificacoesBreakdown } from './useNotificacoes';
import type { AgravoCodigo, BreakdownResponse } from '../../types/api';

// Fixed per-agravo campo pairs — the only place that decides which
// /notificacoes/breakdown campo values this component will ever request.
// DENG/CHIK share gravidade+classi_fin; ANIM uses tra_classi+tp_acidente.
// These columns are physically disjoint per agravo family — the backend
// independently 422s any mismatch — this map guarantees the
// frontend never issues an incompatible request in the first place.
const AGRAVO_CAMPOS: Partial<Record<AgravoCodigo, readonly [string, string]>> = {
  DENG: ['gravidade', 'classi_fin'],
  CHIK: ['gravidade', 'classi_fin'],
  ANIM: ['tra_classi', 'tp_acidente'],
};

const CAMPO_TITLES: Record<string, string> = {
  gravidade: 'Notificações por gravidade',
  classi_fin: 'Notificações por classificação final',
  tra_classi: 'Notificações por classificação do acidente',
  tp_acidente: 'Notificações por tipo de animal',
};

const GRAVE_COLOR = 'var(--neg)';
const NAO_GRAVE_COLOR = 'var(--pos)';
const DEFAULT_BAR_COLOR = 'var(--accent)';

function barColor(campo: string, categoria: string | null): string {
  if (campo === 'gravidade') {
    if (categoria === 'Grave') return GRAVE_COLOR;
    if (categoria === 'Não grave') return NAO_GRAVE_COLOR;
  }
  return DEFAULT_BAR_COLOR;
}

function EmptyState(): React.ReactElement {
  return (
    <div
      style={{
        display: 'flex',
        flexDirection: 'column',
        gap: 'var(--space-1)',
        padding: 'var(--space-2) 0',
        fontFamily: 'var(--font-ui)',
        color: 'var(--text-secondary)',
      }}
    >
      <p style={{ fontSize: 'var(--text-md)', fontWeight: 'var(--weight-semibold)', color: 'var(--text-primary)', margin: 0 }}>
        Nenhuma notificação encontrada
      </p>
      <p style={{ fontSize: 'var(--text-base)', margin: 0 }}>
        Não há notificações para o período e localização selecionados. Ajuste os filtros ou tente outro agravo.
      </p>
    </div>
  );
}

function ErrorState(): React.ReactElement {
  return (
    <div
      style={{
        display: 'flex',
        flexDirection: 'column',
        gap: 'var(--space-1)',
        padding: 'var(--space-2) 0',
        fontFamily: 'var(--font-ui)',
      }}
    >
      <p style={{ fontSize: 'var(--text-md)', fontWeight: 'var(--weight-semibold)', color: 'var(--status-alert)', margin: 0 }}>
        Não foi possível carregar os dados
      </p>
      <p style={{ fontSize: 'var(--text-base)', color: 'var(--text-secondary)', margin: 0 }}>
        Ocorreu um erro ao buscar notificações. Verifique sua conexão e tente novamente.
      </p>
    </div>
  );
}

interface BreakdownChartProps {
  campo: string;
  rows: BreakdownResponse[];
  isLoading: boolean;
  isError: boolean;
}

/**
 * Title + horizontal Recharts BarChart + a plain-text category/count list.
 * The textual list is not decorative — it is the accessible, always-rendered
 * source of truth for category labels (SVG bar labels aren't reliably
 * exposed to assistive tech or to jsdom-based tests that stub out layout).
 */
function BreakdownChart({ campo, rows, isLoading, isError }: BreakdownChartProps): React.ReactElement {
  const title = CAMPO_TITLES[campo] ?? campo;

  return (
    <div style={{ flex: '1 1 260px', minWidth: 0 }}>
      <h3
        style={{
          fontFamily: 'var(--font-ui)',
          fontSize: 'var(--text-md)',
          fontWeight: 'var(--weight-semibold)',
          color: 'var(--text-primary)',
          margin: '0 0 var(--space-2) 0',
        }}
      >
        {title}
      </h3>
      {isLoading ? (
        <LoadingState variant="skeleton-chart" label={`Carregando ${title.toLowerCase()}...`} />
      ) : isError ? (
        <ErrorState />
      ) : rows.length === 0 ? (
        <EmptyState />
      ) : (
        <>
          <div style={{ height: 180 }}>
            <ResponsiveContainer width="100%" height="100%" debounce={50}>
              <BarChart data={rows} layout="vertical" margin={{ top: 4, right: 16, bottom: 4, left: 4 }}>
                <XAxis type="number" allowDecimals={false} tick={{ fontFamily: 'var(--font-mono)', fontSize: 10 }} />
                <YAxis
                  type="category"
                  dataKey="categoria"
                  width={110}
                  tick={{ fontFamily: 'var(--font-ui)', fontSize: 10 }}
                />
                <Tooltip
                  contentStyle={{
                    background: '#1a1d23',
                    border: '1px solid rgba(255,255,255,0.1)',
                    borderRadius: '6px',
                    fontFamily: 'var(--font-ui)',
                    fontSize: '12px',
                    color: '#e2e8f0',
                  }}
                  formatter={(value) => [
                    typeof value === 'number' ? value.toLocaleString('pt-BR') : String(value ?? ''),
                    'Notificações',
                  ]}
                  labelFormatter={(label) => label ?? ''}
                />
                <Bar dataKey="total_notificacoes" isAnimationActive={false}>
                  {rows.map((row, idx) => (
                    <Cell key={`${row.categoria ?? 'null'}-${idx}`} fill={barColor(campo, row.categoria)} />
                  ))}
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          </div>
          <ul
            style={{
              listStyle: 'none',
              margin: 'var(--space-2) 0 0 0',
              padding: 0,
              display: 'flex',
              flexDirection: 'column',
              gap: 'var(--space-1)',
              fontFamily: 'var(--font-ui)',
              fontSize: 'var(--text-xs)',
              color: 'var(--text-secondary)',
            }}
          >
            {rows.map((row, idx) => (
              <li key={`${row.categoria ?? 'null'}-${idx}`} style={{ display: 'flex', justifyContent: 'space-between', gap: 'var(--space-2)' }}>
                <span>{row.categoria ?? 'Ignorado'}</span>
                <span style={{ fontFamily: 'var(--font-mono)' }}>{row.total_notificacoes.toLocaleString('pt-BR')}</span>
              </li>
            ))}
          </ul>
        </>
      )}
    </div>
  );
}

/**
 * Agravo-aware severity/classification breakdown. Renders `null`
 * before issuing any request when no single agravo is selected — the parent
 * VigilanciaPanel already gates mounting on `agravo !== ''`, this is a
 * belt-and-braces guard so the component is safe to mount anywhere.
 */
export function SeverityBreakdown(): React.ReactElement | null {
  const { agravo } = useVigilanciaFilterStore();
  const campos = agravo ? AGRAVO_CAMPOS[agravo] : undefined;

  if (!campos) return null;

  return <SeverityBreakdownCharts campos={campos} />;
}

// Split out so both breakdown hooks run unconditionally on every render
// (the early return above would otherwise skip them).
function SeverityBreakdownCharts({
  campos,
}: {
  campos: readonly [string, string];
}): React.ReactElement {
  const [campoA, campoB] = campos;
  const chartA = useNotificacoesBreakdown(campoA);
  const chartB = useNotificacoesBreakdown(campoB);

  return (
    <div>
      <div style={{ display: 'flex', gap: 'var(--space-6)', flexWrap: 'wrap' }}>
        <BreakdownChart campo={campoA} rows={chartA.rows} isLoading={chartA.isLoading} isError={chartA.isError} />
        <BreakdownChart campo={campoB} rows={chartB.rows} isLoading={chartB.isLoading} isError={chartB.isError} />
      </div>
      <p
        style={{
          fontFamily: 'var(--font-ui)',
          fontSize: 'var(--text-base)',
          color: 'var(--text-muted)',
          margin: 'var(--space-4) 0 0 0',
        }}
      >
        Contagens de notificações registradas no SINAN — não equivalem a casos confirmados.
      </p>
    </div>
  );
}
