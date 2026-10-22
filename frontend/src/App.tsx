import React, { useState, useEffect, useRef } from 'react';
import { Link } from 'react-router-dom';
import './App.css';

import { useFilterStore, hydrateFromUrl, syncToUrl } from './store/filterStore';
import { ErrorBoundary } from './components/ErrorBoundary';
import { Card } from './components/Card';
import { KpiStrip } from './components/KpiStrip';
import { FilterPanel } from './features/filters/FilterPanel';
import { MapView } from './features/map/MapView';
import { DataTable } from './features/map/DataTable';
import { TimeSeriesChart } from './features/forecast/TimeSeriesChart';
import { ClusterScatterPlot } from './features/clusters/ClusterScatterPlot';
import { useQuery } from '@tanstack/react-query';
import { useIndicadores } from './features/map/useIndicadores';
import { fetchMunicipios } from './lib/api';
import { ActiveFilterChips } from './components/ActiveFilterChips';
import type { ForecastResponse, MunicipioResponse } from './types/api';
import { computeMedianByKey, isReliableRow, median, RELIABILITY_RATIO } from './lib/reliability';

// Hydrate store from URL before first render — module-level guard.
// hydrateFromUrl validates all params (unknown params ignored, indicador is
// literal-union validated, ano_* are numeric-guarded) so no arbitrary state injection
// from a shared link is possible.
hydrateFromUrl();

// ─── KPI row — grouped to match mid-row column proportions ───────────────────

function buildKpiForecastUrl(municipio: string, uf: string, indicador: string): string | null {
  if (!municipio && !uf) return null;
  const base = import.meta.env.VITE_API_BASE_URL ?? '';
  const metrica = indicador === 'SIM' ? 'taxa_mortalidade_100k' : 'taxa_internacao_100k';
  if (municipio) return `${base}/forecasts/?municipio=${municipio}&metrica=${metrica}`;
  return `${base}/forecasts/?uf=${uf}&metrica=${metrica}`;
}

// ─── Inner layout ──────────────────────────────────────────────────────────────
interface DashboardContentProps {
  onRegisterExport: (fn: () => void) => void;
}

function DashboardContent({ onRegisterExport }: DashboardContentProps): React.ReactElement {
  const { uf, municipio, ano_inicio, ano_fim, indicador } = useFilterStore();
  // rows here feeds tableRows / CSV export AND KpiStrip (passed down as a prop).
  // MapView and TimeSeriesChart each call useIndicadores() / useHistoricalSeries()
  // internally — the deduplication below never touches their data paths.
  const { rows } = useIndicadores();

  const { data: geoMunicipios = [] } = useQuery<MunicipioResponse[]>({
    queryKey: ['municipios', uf],
    queryFn: () => fetchMunicipios(uf!),
    enabled: !!uf,
    staleTime: 5 * 60 * 1000,
  });
  const coberturaTotal = uf ? geoMunicipios.length : 27;

  const forecastUrl = buildKpiForecastUrl(municipio, uf, indicador);
  const { data: forecastData } = useQuery<ForecastResponse | null>({
    queryKey: ['kpi-forecast', municipio, uf, indicador],
    queryFn: () => fetch(forecastUrl!).then((r) => (r.ok ? r.json() : null)),
    enabled: forecastUrl !== null,
    staleTime: 5 * 60 * 1000,
  });

  const [showTable, setShowTable] = useState(false);

  // Compute % change from first to last year per location — must run before dedup.
  const trendByKey = React.useMemo(() => {
    const groups = new Map<string, typeof rows[number][]>();
    for (const r of rows) {
      const key = r.codigo_ibge ?? r.sigla_uf;
      const g = groups.get(key);
      if (g) g.push(r);
      else groups.set(key, [r]);
    }
    const result = new Map<string, number | null>();
    for (const [key, group] of groups) {
      // A year is only reliable relative to this same location's own history —
      // total_eventos scales wildly by UF/município size and by SIM vs. SIH, so
      // a fixed floor either misses partial-coverage years in large UFs or
      // excludes genuinely sparse-but-real years in small ones. See lib/reliability.ts.
      const locationMedian = median(group.map((r) => r.total_eventos ?? 0));
      const reliable = group.filter((r) => (r.total_eventos ?? 0) >= locationMedian * RELIABILITY_RATIO);
      const sorted = reliable.slice().sort((a, b) => a.ano - b.ano);
      const first = sorted[0];
      const last = sorted[sorted.length - 1];
      if (
        sorted.length >= 2 && first && last && first !== last &&
        first.taxa_por_100k != null && last.taxa_por_100k != null &&
        first.taxa_por_100k !== 0
      ) {
        result.set(key, ((last.taxa_por_100k - first.taxa_por_100k) / Math.abs(first.taxa_por_100k)) * 100);
      } else {
        result.set(key, null);
      }
    }
    return result;
  }, [rows]);

  // Deduplicate rows to one entry per location, keeping the latest year.
  // UF view: one row per município (7-digit IBGE key); national: one row per UF (sigla key).
  // A row is only eligible as the "latest" display row if its total_eventos isn't
  // suspiciously low relative to that location's own median (see lib/reliability.ts) —
  // some UFs/municípios have a partial-coverage year sitting on top of a real complete
  // earlier year; picking that artifact would show a bogus near-zero taxa.
  // Falls back to the unfiltered latest year if a location has no reliable year at all.
  const tableRows = React.useMemo(() => {
    const pickLatest = (
      key: string,
      r: typeof rows[0],
      reliable: Map<string, typeof rows[0]>,
      fallback: Map<string, typeof rows[0]>,
      medianByKey: Map<string, number>
    ) => {
      if (isReliableRow(r, key, medianByKey)) {
        const prev = reliable.get(key);
        if (!prev || r.ano > prev.ano) reliable.set(key, r);
      }
      const prevFallback = fallback.get(key);
      if (!prevFallback || r.ano > prevFallback.ano) fallback.set(key, r);
    };

    if (uf) {
      const relevant = rows.filter((r) => r.codigo_ibge !== null && r.nome_municipio !== null);
      const medianByKey = computeMedianByKey(relevant, (r) => r.codigo_ibge!);
      const reliable = new Map<string, typeof rows[0]>();
      const fallback = new Map<string, typeof rows[0]>();
      for (const r of relevant) {
        pickLatest(r.codigo_ibge!, r, reliable, fallback, medianByKey);
      }
      const latest = new Map<string, typeof rows[0]>([...fallback, ...reliable]);
      return Array.from(latest.values()).map((r) => ({
        codigo_ibge_7: r.codigo_ibge ?? '',
        nome: r.nome_municipio ?? '',
        sigla_uf: r.sigla_uf,
        taxa_por_100k: r.taxa_por_100k,
        ano: r.ano,
        variacao_pct: trendByKey.get(r.codigo_ibge ?? '') ?? null,
      }));
    }
    // National view: API returns one row per (UF, year) — keep latest year per UF.
    const relevant = rows.filter((r) => r.codigo_ibge === null);
    const medianByKey = computeMedianByKey(relevant, (r) => r.sigla_uf);
    const reliable = new Map<string, typeof rows[0]>();
    const fallback = new Map<string, typeof rows[0]>();
    for (const r of relevant) {
      pickLatest(r.sigla_uf, r, reliable, fallback, medianByKey);
    }
    const latest = new Map<string, typeof rows[0]>([...fallback, ...reliable]);
    return Array.from(latest.values()).map((r) => ({
      codigo_ibge_7: r.sigla_uf,
      nome: r.sigla_uf,
      sigla_uf: r.sigla_uf,
      taxa_por_100k: r.taxa_por_100k,
      ano: r.ano,
      variacao_pct: trendByKey.get(r.sigla_uf) ?? null,
    }));
  }, [rows, uf, trendByKey]);

  // Top rows for the compact bottom table — sorted by taxa desc, passed pre-sorted
  const topRows = React.useMemo(
    () => tableRows.slice().sort((a, b) => (b.taxa_por_100k ?? -1) - (a.taxa_por_100k ?? -1)),
    [tableRows]
  );

  const indicadorNome = indicador === 'SIM' ? 'Mortalidade' : 'Internações';
  const tableCaption = uf
    ? `${indicadorNome} por município — ${uf}, ${ano_fim}`
    : `${indicadorNome} por UF — Brasil, ${ano_fim}`;

  // Export CSV — wired to topbar button via exportRef in App
  const handleExportCsv = React.useCallback(() => {
    const header = 'Nome,Sigla UF,Taxa por 100k,Ano início,Ano fim\n';
    const csvRows = tableRows.map((r) => {
      const nome = r.nome.includes(',') ? `"${r.nome}"` : r.nome;
      return `${nome},${r.sigla_uf},${r.taxa_por_100k ?? ''},${ano_inicio},${ano_fim}`;
    });
    const blob = new Blob([header + csvRows.join('\n')], { type: 'text/csv' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `healthlens_${indicador}_${uf || 'brasil'}_${ano_inicio}-${ano_fim}.csv`;
    a.click();
    URL.revokeObjectURL(url);
  }, [tableRows, indicador, uf, ano_inicio, ano_fim]);

  // Register export handler with App so the topbar button can invoke it
  useEffect(() => {
    onRegisterExport(handleExportCsv);
  }, [onRegisterExport, handleExportCsv]);

  // Shared right column — flex: 3/2 split (60/40) avoids fixed-% overflow
  const rightColumn = (
    <div style={{ flex: 1, minWidth: 0, minHeight: 0, display: 'flex', flexDirection: 'column', gap: '10px', overflow: 'hidden' }}>
      <div className="dashboard-chart-card" style={{ flex: 3 }}>
        <Card title="Série Temporal e Previsão" as="section" className="map-fill-card">
          <div style={{ flex: 1, minHeight: 0, display: 'flex', flexDirection: 'column' }}>
            <ErrorBoundary context="gráfico" fallbackTitle="Erro ao carregar gráfico">
              <TimeSeriesChart />
            </ErrorBoundary>
          </div>
          {ano_inicio <= 2022 && ano_fim >= 2021 && (
            <p
              role="note"
              style={{
                flexShrink: 0,
                margin: '4px 0 0',
                textAlign: 'right',
                fontFamily: 'var(--font-ui)',
                fontSize: 'var(--text-xs)',
                color: 'var(--text-muted)',
              }}
            >
              ⓘ 2021–2022 não disponíveis na demo
            </p>
          )}
        </Card>
      </div>
      <div className="dashboard-chart-card" style={{ flex: 2 }}>
        <ClusterScatterPlot />
      </div>
    </div>
  );

  return (
    <main className="dashboard-main">
      {/* Toggle + filter chips */}
      <div className="dashboard-tab-row" style={{ display: 'flex', alignItems: 'center', gap: 12, flexWrap: 'wrap' }}>
        <div className="tab-segmented">
          <button
            type="button"
            aria-label="Alternar entre mapa e tabela"
            className={`tab-btn${!showTable ? ' active' : ''}`}
            aria-pressed={!showTable}
            onClick={() => setShowTable(false)}
          >
            Mapa
          </button>
          <button
            type="button"
            className={`tab-btn${showTable ? ' active' : ''}`}
            aria-pressed={showTable}
            onClick={() => setShowTable(true)}
          >
            Tabela
          </button>
        </div>
        <ActiveFilterChips />
      </div>

      {/* KPI strip — two groups matching mid-row column proportions */}
      <div className="dashboard-kpi-row">
        <KpiStrip
          rows={rows}
          forecasts={forecastData}
          uf={uf}
          municipio={municipio}
          anoInicio={ano_inicio}
          anoFim={ano_fim}
          indicador={indicador}
          coberturaTotal={coberturaTotal}
        />
      </div>
      <p className="demo-dataset-note">
        <span aria-hidden="true">ⓘ</span> Demo uses a partial dataset due to free-tier storage limits. Full pipeline runs locally.
      </p>

      {showTable ? (
        <>
          <div className="dashboard-mid-row">
            <div style={{
              flex: 1,
              minWidth: 0,
              minHeight: 0,
              display: 'flex',
              flexDirection: 'column',
              overflow: 'hidden',
              background: '#10151D',
              borderRadius: 12,
              border: '1px solid rgba(255,255,255,0.06)',
            }}>
              <DataTable rows={tableRows} caption={tableCaption} />
            </div>
            {rightColumn}
          </div>
        </>
      ) : (
        <>
          <div className="dashboard-mid-row">
            <div style={{ flex: 1.15, minWidth: 0, minHeight: 0, display: 'flex', flexDirection: 'column', overflow: 'hidden', margin: 0, padding: 0 }}>
              <div className="map-fill-card" style={{ margin: 0, padding: 16, boxShadow: 'var(--shadow-card)' }}>
                <ErrorBoundary context="mapa" fallbackTitle="Erro ao carregar mapa">
                  <MapView />
                </ErrorBoundary>
              </div>
            </div>
            {rightColumn}
          </div>
          <div className="dashboard-bottom-table">
            <DataTable
              rows={topRows}
              caption={tableCaption}
              maxRows={5}
              onFooterClick={() => setShowTable(true)}
            />
          </div>
        </>
      )}
    </main>
  );
}

// ─── App root ──────────────────────────────────────────────────────────────────
export default function App(): React.ReactElement {
  const { uf } = useFilterStore();
  const exportRef = useRef<(() => void) | null>(null);

  // Subscribe URL sync after mount — fires on every filter change.
  useEffect(() => {
    const unsub = useFilterStore.subscribe((state) => syncToUrl(state));
    return unsub;
  }, []);

  return (
    <div className="app-root">
      {/* Topbar — brand + breadcrumb + Export CSV */}
      <header className="dashboard-topbar">
        <div className="topbar-left">
          <Link to="/" className="topbar-brand" style={{ textDecoration: 'none', color: 'inherit' }}>
            HealthLens
          </Link>
          <span className="topbar-breadcrumb">
            Brasil{uf ? <> › <span>{uf}</span></> : null}
          </span>
        </div>
        <div className="topbar-right">
          <Link
            to="/vigilancia"
            style={{
              fontFamily: 'var(--font-ui)',
              fontSize: 'var(--text-xs)',
              fontWeight: 600,
              textTransform: 'uppercase',
              letterSpacing: '.5px',
              color: 'var(--text-muted)',
              textDecoration: 'none',
              marginRight: 16,
            }}
          >
            · Vigilância Epidemiológica
          </Link>
          <button
            type="button"
            className="btn-export"
            onClick={() => exportRef.current?.()}
            aria-label="Exportar dados como CSV"
          >
            ↓ Exportar CSV
          </button>
        </div>
      </header>

      {/* Body: sidebar + main content */}
      <div className="dashboard-body">
        <aside className="dashboard-sidebar">
          <FilterPanel />
        </aside>
        <DashboardContent onRegisterExport={(fn) => { exportRef.current = fn; }} />
      </div>
    </div>
  );
}
