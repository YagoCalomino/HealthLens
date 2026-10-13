import React from 'react';
import { useQuery } from '@tanstack/react-query';
import { fetchNotificacoesPage } from '../../lib/api';
import { LoadingState } from '../../components/LoadingState';
import { useVigilanciaFilterStore } from '../../store/vigilanciaFilterStore';
import type { AgravoCodigo, NotificacaoResponse } from '../../types/api';

const AGRAVO_LABELS: Record<AgravoCodigo, string> = {
  DENG: 'Dengue',
  CHIK: 'Chikungunya',
  ANIM: 'Animais peçonhentos',
};

const CSV_HEADER = [
  'Município',
  'UF',
  'Data de notificação',
  'Semana epidemiológica',
  'Agravo',
  'Sexo',
  'Faixa etária',
  'Classificação',
  'Gravidade',
];

function decodeSexo(v: string | null): string {
  if (v === 'M') return 'Masculino';
  if (v === 'F') return 'Feminino';
  return 'Ignorado';
}

function decodeGravidade(v: boolean | null): string {
  if (v === true) return 'Grave';
  if (v === false) return 'Não grave';
  return '';
}

/** "Classificação" is agravo-dependent (classi_fin for DENG/CHIK, tra_classi for ANIM) —
 * exactly one of the two is ever non-null for a given row (disjoint-column model). */
function classificacao(row: NotificacaoResponse): string {
  return row.classi_fin_label ?? row.tra_classi_label ?? '';
}

/** "Gravidade" mirrors classificacao's per-agravo split: gravidade_grave for DENG/CHIK,
 * tp_acidente_label (the closest ANIM-side severity signal) as the fallback for ANIM. */
function gravidade(row: NotificacaoResponse): string {
  const decoded = decodeGravidade(row.gravidade_grave);
  if (decoded) return decoded;
  return row.tp_acidente_label ?? '';
}

function formatDate(dt: string | null): string {
  if (!dt) return '';
  const [ano, mes, dia] = dt.split('-');
  if (!ano || !mes || !dia) return dt;
  return `${dia}/${mes}/${ano}`;
}

/** Quotes any field containing a comma — the only escaping the plan's threat
 * model requires: every value here comes from dim_local/dim_agravo/
 * app.constants.sinan decoded server-side, never free client-supplied text. */
function csvField(value: string): string {
  return value.includes(',') ? `"${value}"` : value;
}

function rowToCsvLine(row: NotificacaoResponse): string {
  const fields = [
    row.nome_municipio ?? '',
    row.sigla_uf,
    row.dt_notific ?? '',
    row.semana_epidemiologica != null ? String(row.semana_epidemiologica) : '',
    AGRAVO_LABELS[row.agravo] ?? row.agravo,
    decodeSexo(row.sexo),
    row.faixa_etaria ?? '',
    classificacao(row),
    gravidade(row),
  ];
  return fields.map(csvField).join(',');
}

/** Pure CSV builder — unit-testable without touching the DOM. Mirrors
 * App.tsx::handleExportCsv's conventions: header line, comma-quoting, \n joins. */
export function buildNotificacoesCsv(rows: NotificacaoResponse[]): string {
  const lines = [CSV_HEADER.join(','), ...rows.map(rowToCsvLine)];
  return lines.join('\n');
}

function PromptState(): React.ReactElement {
  return (
    <p
      style={{
        fontFamily: 'var(--font-ui)',
        fontSize: 'var(--text-base)',
        color: 'var(--text-muted)',
        margin: 0,
      }}
    >
      Selecione uma UF ou município para listar os registros de notificações.
    </p>
  );
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

const tableStyle: React.CSSProperties = {
  width: '100%',
  borderCollapse: 'collapse',
  fontFamily: 'var(--font-ui)',
  fontSize: 'var(--text-base)',
  color: 'var(--text-primary)',
};

const thStyle: React.CSSProperties = {
  fontFamily: 'var(--font-ui)',
  fontSize: 10.5,
  fontWeight: 600,
  color: 'var(--text-muted)',
  textTransform: 'uppercase',
  letterSpacing: '.5px',
  padding: 'var(--space-2) var(--space-4)',
  textAlign: 'left',
  whiteSpace: 'nowrap',
  borderBottom: '1px solid rgba(255,255,255,.06)',
};

const tdStyle: React.CSSProperties = {
  padding: 'var(--space-2) var(--space-4)',
  borderBottom: '1px solid rgba(255,255,255,.04)',
};

const exportButtonStyle: React.CSSProperties = {
  fontFamily: 'var(--font-ui)',
  fontSize: 'var(--text-base)',
  fontWeight: 'var(--weight-semibold)' as unknown as number,
  background: 'var(--accent)',
  color: '#ffffff',
  border: 'none',
  borderRadius: 'var(--radius-md)',
  padding: 'var(--space-2) var(--space-4)',
  cursor: 'pointer',
};

/**
 * Raw-record drill-down + CSV export. Fetches through
 * fetchNotificacoesPage, which fetches only the first page (up to 50
 * records) to avoid timeouts with high-volume agravos like DENG. CSV
 * export covers this first page only. Gated: only fetches when a uf or
 * município filter is active, so the default national view never pulls the
 * whole table.
 */
export function NotificacoesTable(): React.ReactElement {
  const { agravo, uf, municipio, classi_fin, ano_inicio, ano_fim } = useVigilanciaFilterStore();
  const filters = { agravo, uf, municipio, classi_fin, ano_inicio, ano_fim };
  const enabled = Boolean(uf || municipio);

  const { data, isLoading, isError } = useQuery({
    queryKey: ['notificacoes-page', filters],
    queryFn: () => fetchNotificacoesPage(filters),
    enabled,
    staleTime: 10 * 60 * 1000,
    retry: 1,
    gcTime: 10 * 60 * 1000,
  });

  const rows = data ?? [];

  const handleExport = (): void => {
    const csv = buildNotificacoesCsv(rows);
    const blob = new Blob([csv], { type: 'text/csv' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `healthlens_notificacoes_${agravo || 'todos'}_${uf || 'brasil'}_${ano_inicio}-${ano_fim}.csv`;
    a.click();
    URL.revokeObjectURL(url);
  };

  if (!enabled) {
    return <PromptState />;
  }

  if (isLoading) {
    return <LoadingState variant="skeleton-table" label="Carregando notificações..." />;
  }

  if (isError) {
    return <ErrorState />;
  }

  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'flex-end', marginBottom: 'var(--space-2)' }}>
        <button type="button" onClick={handleExport} disabled={rows.length === 0} style={exportButtonStyle}>
          Exportar CSV
        </button>
      </div>
      {rows.length === 0 ? (
        <EmptyState />
      ) : (
        <div style={{ overflowX: 'auto' }}>
          <table style={tableStyle} aria-label="Notificações — registros">
            <thead>
              <tr>
                <th scope="col" style={thStyle}>Município</th>
                <th scope="col" style={thStyle}>UF</th>
                <th scope="col" style={thStyle}>Data de notificação</th>
                <th scope="col" style={thStyle}>Semana epidemiológica</th>
                <th scope="col" style={thStyle}>Agravo</th>
                <th scope="col" style={thStyle}>Sexo</th>
                <th scope="col" style={thStyle}>Faixa etária</th>
                <th scope="col" style={thStyle}>Classificação</th>
                <th scope="col" style={thStyle}>Gravidade</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((row) => (
                <tr key={row.id}>
                  <td style={tdStyle}>{row.nome_municipio ?? '—'}</td>
                  <td style={tdStyle}>{row.sigla_uf}</td>
                  <td style={tdStyle}>{formatDate(row.dt_notific) || '—'}</td>
                  <td style={tdStyle}>{row.semana_epidemiologica ?? '—'}</td>
                  <td style={tdStyle}>{AGRAVO_LABELS[row.agravo] ?? row.agravo}</td>
                  <td style={tdStyle}>{decodeSexo(row.sexo)}</td>
                  <td style={tdStyle}>{row.faixa_etaria ?? '—'}</td>
                  <td style={tdStyle}>{classificacao(row) || '—'}</td>
                  <td style={tdStyle}>{gravidade(row) || '—'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
