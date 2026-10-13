import React, { useMemo, useState } from 'react';
import { getQuantileScale, CHORO_5, NO_DATA_COLOR } from '../../lib/choropleth';

export interface DataTableRow {
  codigo_ibge_7: string;
  nome: string;
  sigla_uf: string;
  taxa_por_100k: number | null;
  ano: number;
  variacao_pct?: number | null;
}

export interface DataTableProps {
  rows: DataTableRow[];
  /** Required caption — describes the current filter context (e.g. "Mortalidade — SP, 2022"). */
  caption: string;
  /** When set, renders a compact 5-row preview with no search/sort/pagination. */
  maxRows?: number;
  /** Called when the "Ver todos" footer link is clicked (only shown when maxRows is set). */
  onFooterClick?: () => void;
}

const PAGE_SIZE = 20;

type SortCol = 'nome' | 'taxa_por_100k' | 'ano' | null;

function buildTrendMap(rows: DataTableRow[]): Map<string, number | null> {
  const groups = new Map<string, DataTableRow[]>();
  for (const row of rows) {
    const key = row.codigo_ibge_7;
    const group = groups.get(key);
    if (group) group.push(row);
    else groups.set(key, [row]);
  }
  const result = new Map<string, number | null>();
  for (const [key, group] of groups) {
    const sorted = group.slice().sort((a, b) => a.ano - b.ano);
    const first = sorted[0];
    const last = sorted[sorted.length - 1];
    if (
      first &&
      last &&
      first !== last &&
      first.taxa_por_100k != null &&
      last.taxa_por_100k != null &&
      first.taxa_por_100k !== 0
    ) {
      result.set(key, ((last.taxa_por_100k - first.taxa_por_100k) / Math.abs(first.taxa_por_100k)) * 100);
    } else {
      result.set(key, null);
    }
  }
  return result;
}

const tableStyle: React.CSSProperties = {
  width: '100%',
  borderCollapse: 'collapse',
  fontFamily: 'var(--font-ui)',
  fontSize: 'var(--text-base)',
  color: 'var(--text-primary)',
};

const thBase: React.CSSProperties = {
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

const thNumeric: React.CSSProperties = { ...thBase, textAlign: 'right' };

const tdBase: React.CSSProperties = {
  padding: 'var(--space-2) var(--space-4)',
  borderBottom: '1px solid rgba(255,255,255,.04)',
};

const tdNumeric: React.CSSProperties = {
  ...tdBase,
  fontFamily: 'var(--font-mono)',
  textAlign: 'right',
  fontWeight: 600,
};

const tdNull: React.CSSProperties = {
  ...tdBase,
  fontFamily: 'var(--font-mono)',
  textAlign: 'right',
  color: 'var(--text-muted)',
};

function SortableHeader({
  col,
  label,
  sortCol,
  sortDir,
  onSort,
  numeric = false,
}: {
  col: SortCol & string;
  label: string;
  sortCol: SortCol;
  sortDir: 'asc' | 'desc';
  onSort: (c: string) => void;
  numeric?: boolean;
}): React.ReactElement {
  const isActive = sortCol === col;
  const arrow = isActive ? (sortDir === 'asc' ? ' ↑' : ' ↓') : '';
  return (
    <th scope="col" style={numeric ? thNumeric : thBase}>
      <button
        type="button"
        onClick={() => onSort(col)}
        style={{
          fontFamily: 'var(--font-ui)',
          fontSize: 10.5,
          fontWeight: 600,
          color: isActive ? 'var(--text-primary)' : 'var(--text-muted)',
          textTransform: 'uppercase',
          letterSpacing: '.5px',
          background: 'none',
          border: 'none',
          padding: 0,
          cursor: 'pointer',
          textAlign: numeric ? 'right' : 'left',
          width: '100%',
        }}
        aria-sort={isActive ? (sortDir === 'asc' ? 'ascending' : 'descending') : 'none'}
      >
        {label}{arrow}
      </button>
    </th>
  );
}

export function DataTable({ rows, caption, maxRows, onFooterClick }: DataTableProps): React.ReactElement {
  const [search, setSearch] = useState('');
  const [sortCol, setSortCol] = useState<SortCol>(null);
  const [sortDir, setSortDir] = useState<'asc' | 'desc'>('asc');
  const [page, setPage] = useState(0);

  const { color: colorFn } = useMemo(
    () => getQuantileScale(rows.map((r) => r.taxa_por_100k), CHORO_5),
    [rows]
  );
  const trendMap = useMemo(() => buildTrendMap(rows), [rows]);

  const handleSort = (col: string) => {
    const c = col as SortCol;
    if (sortCol === c) {
      if (sortDir === 'asc') setSortDir('desc');
      else { setSortCol(null); setSortDir('asc'); }
    } else {
      setSortCol(c);
      setSortDir('asc');
    }
    setPage(0);
  };

  const filtered = useMemo(() => {
    const q = search.toLowerCase();
    let result = q ? rows.filter((r) => r.nome.toLowerCase().includes(q)) : rows;
    if (sortCol) {
      result = result.slice().sort((a, b) => {
        const aVal = a[sortCol as keyof DataTableRow];
        const bVal = b[sortCol as keyof DataTableRow];
        if (aVal == null && bVal == null) return 0;
        if (aVal == null) return 1;
        if (bVal == null) return -1;
        const cmp = aVal < bVal ? -1 : aVal > bVal ? 1 : 0;
        return sortDir === 'asc' ? cmp : -cmp;
      });
    }
    return result;
  }, [rows, search, sortCol, sortDir]);

  const totalPages = Math.max(1, Math.ceil(filtered.length / PAGE_SIZE));
  const safePage = Math.min(page, totalPages - 1);
  const visibleRows = filtered.slice(safePage * PAGE_SIZE, (safePage + 1) * PAGE_SIZE);

  // Compact preview — no search/sort/pagination, no scroll
  if (maxRows !== undefined) {
    const compactRows = rows.slice(0, maxRows);
    return (
      <div style={{ flex: 1, minHeight: 0, display: 'flex', flexDirection: 'column' }}>
        <div style={{ overflow: 'hidden', flex: 1, minHeight: 0 }}>
          <table style={tableStyle} aria-label={caption}>
            <caption style={{ display: 'none' }}>{caption}</caption>
            <thead>
              <tr>
                <th scope="col" style={thBase}>Nome</th>
                <th scope="col" style={thBase}>UF</th>
                <th scope="col" style={thNumeric}>Taxa / 100k</th>
                <th scope="col" style={thNumeric}>Tendência</th>
                <th scope="col" style={thNumeric}>Ano</th>
              </tr>
            </thead>
            <tbody>
              {compactRows.map((row) => (
                <TableRow key={row.codigo_ibge_7 + row.ano} row={row} colorFn={colorFn} trendMap={trendMap} />
              ))}
            </tbody>
          </table>
        </div>
        {rows.length > maxRows && onFooterClick && (
          <div
            role="button"
            tabIndex={0}
            onClick={onFooterClick}
            onKeyDown={(e) => { if (e.key === 'Enter') onFooterClick(); }}
            style={{
              flexShrink: 0,
              padding: '8px 16px',
              fontSize: 11.5,
              color: 'var(--accent)',
              cursor: 'pointer',
              borderTop: '1px solid rgba(255,255,255,0.06)',
              textAlign: 'right',
            }}
          >
            Ver todos {rows.length} registros na Tabela →
          </div>
        )}
      </div>
    );
  }

  return (
    <div style={{ flex: 1, minHeight: 0, display: 'flex', flexDirection: 'column' }}>
      <input
        type="text"
        placeholder="Buscar..."
        value={search}
        onChange={(e) => { setSearch(e.target.value); setPage(0); }}
        style={{
          fontFamily: 'var(--font-ui)',
          fontSize: 12.5,
          background: 'var(--surface-control)',
          border: '1px solid var(--border-control)',
          borderRadius: 'var(--radius-md)',
          color: 'var(--text-primary)',
          padding: '7px 12px',
          width: '100%',
          boxSizing: 'border-box',
          marginBottom: 10,
          outline: 'none',
        }}
      />
      <div style={{ overflowY: 'auto', flex: 1, minHeight: 0 }}>
        <table style={tableStyle} aria-label={caption}>
          <caption style={{ display: 'none' }}>{caption}</caption>
          <thead>
            <tr>
              <SortableHeader col="nome" label="Nome" sortCol={sortCol} sortDir={sortDir} onSort={handleSort} />
              <th scope="col" style={thBase}>UF</th>
              <SortableHeader col="taxa_por_100k" label="Taxa / 100k" sortCol={sortCol} sortDir={sortDir} onSort={handleSort} numeric />
              <th scope="col" style={thNumeric}>Tendência</th>
              <SortableHeader col="ano" label="Ano" sortCol={sortCol} sortDir={sortDir} onSort={handleSort} numeric />
            </tr>
          </thead>
          <tbody>
            {visibleRows.map((row) => (
              <TableRow key={row.codigo_ibge_7 + row.ano} row={row} colorFn={colorFn} trendMap={trendMap} />
            ))}
            {filtered.length === 0 && (
              <tr>
                <td
                  colSpan={5}
                  style={{ ...tdBase, textAlign: 'center', color: 'var(--text-secondary)', fontStyle: 'italic' }}
                >
                  Sem dados para os filtros selecionados.
                </td>
              </tr>
            )}
          </tbody>
        </table>
        {rows.length < 10 && rows.length > 0 && (
          <div
            style={{
              padding: '20px 16px',
              color: 'var(--text-muted)',
              fontSize: 12,
              textAlign: 'center',
              fontFamily: 'var(--font-ui)',
            }}
          >
            Selecione uma UF para ver todos os municípios
          </div>
        )}
      </div>
      {totalPages > 1 && (
        <div
          style={{
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
            padding: '8px var(--space-4)',
            fontFamily: 'var(--font-ui)',
            fontSize: 12,
            color: 'var(--text-secondary)',
          }}
        >
          <button
            type="button"
            onClick={() => setPage((p) => Math.max(0, p - 1))}
            disabled={safePage === 0}
            style={{
              fontFamily: 'var(--font-ui)',
              fontSize: 12,
              background: 'none',
              border: '1px solid var(--border-control)',
              borderRadius: 'var(--radius-md)',
              color: safePage === 0 ? 'var(--text-muted)' : 'var(--text-secondary)',
              padding: '4px 10px',
              cursor: safePage === 0 ? 'default' : 'pointer',
            }}
          >
            Anterior
          </button>
          <span>Página {safePage + 1} de {totalPages}</span>
          <button
            type="button"
            onClick={() => setPage((p) => Math.min(totalPages - 1, p + 1))}
            disabled={safePage >= totalPages - 1}
            style={{
              fontFamily: 'var(--font-ui)',
              fontSize: 12,
              background: 'none',
              border: '1px solid var(--border-control)',
              borderRadius: 'var(--radius-md)',
              color: safePage >= totalPages - 1 ? 'var(--text-muted)' : 'var(--text-secondary)',
              padding: '4px 10px',
              cursor: safePage >= totalPages - 1 ? 'default' : 'pointer',
            }}
          >
            Próxima
          </button>
        </div>
      )}
    </div>
  );
}

function TableRow({
  row,
  colorFn,
  trendMap,
}: {
  row: DataTableRow;
  colorFn: (v: number | null) => string;
  trendMap: Map<string, number | null>;
}): React.ReactElement {
  const [hovered, setHovered] = React.useState(false);
  const trend = row.variacao_pct !== undefined ? row.variacao_pct : (trendMap.get(row.codigo_ibge_7) ?? null);
  const dotColor = row.taxa_por_100k != null ? colorFn(row.taxa_por_100k) : NO_DATA_COLOR;

  const rowStyle: React.CSSProperties = {
    backgroundColor: hovered ? 'rgba(255,255,255,.025)' : 'transparent',
  };

  return (
    <tr style={rowStyle} onMouseEnter={() => setHovered(true)} onMouseLeave={() => setHovered(false)}>
      <td style={tdBase}>
        <div style={{ display: 'flex', alignItems: 'center' }}>
          <span
            style={{
              display: 'inline-block',
              width: 8,
              height: 8,
              borderRadius: 2,
              background: dotColor,
              flexShrink: 0,
              marginRight: 6,
            }}
          />
          {row.nome}
        </div>
      </td>
      <td style={tdBase}>{row.sigla_uf}</td>
      {row.taxa_por_100k != null ? (
        <td style={tdNumeric}>
          {row.taxa_por_100k.toLocaleString('pt-BR', { minimumFractionDigits: 1, maximumFractionDigits: 1 })}
        </td>
      ) : (
        <td style={tdNull}>—</td>
      )}
      {trend != null ? (
        <td style={{ ...tdNumeric, color: trend > 0 ? 'var(--neg)' : 'var(--pos)' }}>
          {trend > 0 ? '▲' : '▼'} {Math.abs(trend).toFixed(1)}%
        </td>
      ) : (
        <td style={tdNull}>—</td>
      )}
      <td style={tdNumeric}>{row.ano}</td>
    </tr>
  );
}
