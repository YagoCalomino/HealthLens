import React from 'react';
import { Bar, BarChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts';
import { LoadingState } from '../../components/LoadingState';
import { useNotificacoesBreakdown } from './useNotificacoes';
import type { BreakdownResponse } from '../../types/api';

const CAMPO_TITLES: Record<string, string> = {
  faixa_etaria: 'Notificações por faixa etária',
  sexo: 'Notificações por sexo',
};

const BAR_COLOR = 'var(--accent)';

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
 * The textual list is the accessible, always-rendered source of truth for
 * category labels (SVG bar labels aren't reliably exposed to assistive tech
 * or to jsdom-based tests that stub out layout).
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
                    background: 'var(--surface-raised)',
                    border: '1px solid var(--border-subtle)',
                    fontFamily: 'var(--font-ui)',
                    fontSize: 'var(--text-base)',
                  }}
                />
                <Bar dataKey="total_notificacoes" fill={BAR_COLOR} isAnimationActive={false} />
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
 * Faixa-etária + sexo breakdown — agravo-agnostic (renders for any agravo
 * state including ''). Unlike SeverityBreakdown, these two campos
 * are valid for every agravo, so there is no compatibility gate here.
 */
export function AgeSexBreakdown(): React.ReactElement {
  const faixaEtaria = useNotificacoesBreakdown('faixa_etaria');
  const sexo = useNotificacoesBreakdown('sexo');

  return (
    <div style={{ display: 'flex', gap: 'var(--space-6)', flexWrap: 'wrap' }}>
      <BreakdownChart campo="faixa_etaria" rows={faixaEtaria.rows} isLoading={faixaEtaria.isLoading} isError={faixaEtaria.isError} />
      <BreakdownChart campo="sexo" rows={sexo.rows} isLoading={sexo.isLoading} isError={sexo.isError} />
    </div>
  );
}
