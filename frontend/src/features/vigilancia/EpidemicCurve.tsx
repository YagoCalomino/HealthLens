import React from 'react';
import { Legend, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts';
import { useVigilanciaFilterStore } from '../../store/vigilanciaFilterStore';
import { useNotificacoesCurva } from './useNotificacoes';
import type { AgravoCodigo, CurvaEpidemicaResponse } from '../../types/api';

const TOTAL_SEMANAS = 53;

// Same agravo-identity colors used across every per-agravo surface
// (MultiAgravoCard.tsx AGRAVO_COLORS) — must stay consistent, never redefined differently.
const AGRAVO_COLORS: Record<AgravoCodigo, string> = {
  DENG: '#3F6FFF',
  CHIK: '#F0B35B',
  ANIM: '#4FD1B0',
};

export type CurvaChartRow = { semana: number } & Record<string, number | null>;

/**
 * Pivots a flat CurvaEpidemicaResponse[] into 53 rows (semana 1..53), one
 * numeric column per distinct ano_epidemiologico present in the data.
 *
 * A week with no row for a given year is `null` (renders as a line gap); a
 * week with an explicit `total_notificacoes: 0` row is `0` (renders as a zero
 * point). That distinction is the whole reason the backend
 * zero-fills every epi-week server-side — losing it here would silently turn
 * "no notifications this week" into "no data this week".
 */
export function buildCurvaChartData(rows: CurvaEpidemicaResponse[]): CurvaChartRow[] {
  const anos = Array.from(new Set(rows.map((r) => r.ano_epidemiologico))).sort((a, b) => a - b);

  const bySemanaAno = new Map<number, Map<number, number>>();
  for (const row of rows) {
    let byAno = bySemanaAno.get(row.semana_epidemiologica);
    if (!byAno) {
      byAno = new Map();
      bySemanaAno.set(row.semana_epidemiologica, byAno);
    }
    byAno.set(row.ano_epidemiologico, row.total_notificacoes);
  }

  const result: CurvaChartRow[] = [];
  for (let semana = 1; semana <= TOTAL_SEMANAS; semana++) {
    const point: CurvaChartRow = { semana };
    const byAno = bySemanaAno.get(semana);
    for (const ano of anos) {
      const value = byAno?.get(ano);
      point[String(ano)] = value === undefined ? null : value;
    }
    result.push(point);
  }
  return result;
}

function EmptyCurva(): React.ReactElement {
  return (
    <div
      style={{
        display: 'flex',
        flexDirection: 'column',
        alignItems: 'center',
        justifyContent: 'center',
        height: 220,
        gap: 'var(--space-1)',
        color: 'var(--text-secondary)',
        fontFamily: 'var(--font-ui)',
        textAlign: 'center',
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

function FetchError(): React.ReactElement {
  return (
    <div
      style={{
        display: 'flex',
        flexDirection: 'column',
        alignItems: 'center',
        justifyContent: 'center',
        height: 220,
        gap: 'var(--space-1)',
        color: 'var(--text-secondary)',
        fontFamily: 'var(--font-ui)',
        textAlign: 'center',
      }}
    >
      <p style={{ fontSize: 'var(--text-md)', fontWeight: 'var(--weight-semibold)', color: 'var(--status-alert)', margin: 0 }}>
        Não foi possível carregar os dados
      </p>
      <p style={{ fontSize: 'var(--text-base)', margin: 0 }}>
        Ocorreu um erro ao buscar notificações. Verifique sua conexão e tente novamente.
      </p>
    </div>
  );
}

// De-emphasized stroke for prior (non-current) epidemiological years — --text-muted family.
const PRIOR_YEAR_STROKE = 'var(--text-muted)';

/**
 * Epidemic curve by semana epidemiológica — one line per
 * ano_epidemiologico, shared X axis of week 1..53. The most recent year
 * renders in the selected agravo's identity color at full opacity; prior
 * years render de-emphasized so the current season stands out.
 */
export function EpidemicCurve(): React.ReactElement {
  const { agravo } = useVigilanciaFilterStore();
  const { rows, isLoading, isError } = useNotificacoesCurva();

  if (isLoading) {
    return (
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          height: 220,
          color: 'var(--text-secondary)',
          fontFamily: 'var(--font-ui)',
          fontSize: 'var(--text-base)',
        }}
      >
        Carregando curva epidêmica...
      </div>
    );
  }

  if (isError) return <FetchError />;
  if (rows.length === 0) return <EmptyCurva />;

  const chartData = buildCurvaChartData(rows);
  const anos = Array.from(new Set(rows.map((r) => r.ano_epidemiologico))).sort((a, b) => a - b);
  const latestAno = anos[anos.length - 1];
  const currentColor = agravo ? AGRAVO_COLORS[agravo] : 'var(--accent)';

  return (
    <div style={{ height: 260 }}>
      <ResponsiveContainer width="100%" height="100%" debounce={50}>
        <LineChart data={chartData} margin={{ top: 8, right: 24, bottom: 0, left: 0 }}>
          <XAxis
            dataKey="semana"
            type="number"
            domain={[1, TOTAL_SEMANAS]}
            tick={{ fontFamily: 'var(--font-mono)', fontSize: 10 }}
          />
          <YAxis
            label={{ value: 'Notificações', angle: -90, position: 'insideLeft', fontSize: 10, fill: 'var(--text-muted)' }}
            tick={{ fontFamily: 'var(--font-mono)', fontSize: 10 }}
            allowDecimals={false}
          />
          <Tooltip
            labelFormatter={(v) => `Semana ${v}`}
            contentStyle={{
              background: 'var(--surface-raised)',
              border: '1px solid var(--border-subtle)',
              fontFamily: 'var(--font-ui)',
              fontSize: 'var(--text-base)',
            }}
          />
          <Legend wrapperStyle={{ fontFamily: 'var(--font-ui)', fontSize: 'var(--text-xs)' }} />
          {anos.map((ano, i) => {
            const isLatest = ano === latestAno;
            return (
              <Line
                key={ano}
                type="monotone"
                dataKey={String(ano)}
                name={String(ano)}
                stroke={isLatest ? currentColor : PRIOR_YEAR_STROKE}
                strokeWidth={isLatest ? 2 : 1.5}
                strokeOpacity={isLatest ? 1 : Math.max(0.3, 0.7 - i * 0.15)}
                dot={false}
                connectNulls={false}
                isAnimationActive={false}
              />
            );
          })}
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}
