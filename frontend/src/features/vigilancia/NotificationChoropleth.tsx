import React, { useCallback, useMemo, useState } from 'react';
import { ComposableMap, ZoomableGroup } from 'react-simple-maps';
import { geoMercator } from 'd3-geo';
import { feature } from 'topojson-client';
import type { Topology } from 'topojson-specification';
import type { FeatureCollection, Geometry } from 'geojson';
import { Legend } from '../../components/Legend';
import { LoadingState } from '../../components/LoadingState';
import { getQuantileScale, CHORO_5 } from '../../lib/choropleth';
import { Breadcrumb } from '../map/Breadcrumb';
import { ChoroplethLayer, type ChoroplethRow } from '../map/ChoroplethLayer';
import { useVigilanciaFilterStore } from '../../store/vigilanciaFilterStore';
import { useNotificacoesMunicipioSummary, useNotificacoesUfSummary } from './useNotificacoes';
import type { NotificacaoSummaryResponse } from '../../types/api';

// Fixed projection for the national (27 UF) view — mirrors the mortalidade map's national projection config.
const NATIONAL_PROJ = { rotate: [0, 0, 0] as [number, number, number], scale: 750, center: [-54, -14] as [number, number] };
const DEFAULT_CENTER: [number, number] = [-54, -15];
const DEFAULT_ZOOM = 1;

interface TooltipInfo {
  nome: string;
  taxa: number | null;
  ano: number;
  x: number;
  y: number;
}

/**
 * Collapses (…, ano) summary rows to a single byCode map, keeping each
 * code's own latest ano within the filtered range — the map shows one
 * year's rate per code, never a cross-period sum, but falls back
 * per-UF/município so a code without data in the global latest ano still
 * shows its own most recent year instead of "sem dados". Returns the
 * global latest ano alongside the map so the caller can label the period.
 */
export function collapseToLatestAno(
  rows: NotificacaoSummaryResponse[]
): { byCode: Map<string, ChoroplethRow>; latestAno: number | null } {
  if (rows.length === 0) return { byCode: new Map(), latestAno: null };
  const latestAno = Math.max(...rows.map((r) => r.ano));
  const byCode = new Map<string, ChoroplethRow>();
  // Group by code, keep latest ano per code
  for (const row of rows) {
    const key = row.codigo_ibge ?? row.sigla_uf;
    if (!key) continue;
    const existing = byCode.get(key);
    if (!existing || row.ano > existing.ano) {
      byCode.set(key, { taxa_por_100k: row.taxa_por_100k, ano: row.ano });
    }
  }
  return { byCode, latestAno };
}

function EmptyState(): React.ReactElement {
  return (
    <div
      style={{
        display: 'flex',
        flexDirection: 'column',
        alignItems: 'center',
        justifyContent: 'center',
        height: 400,
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
        height: 400,
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

function NotificationTooltip({ nome, taxa, ano, x, y }: TooltipInfo): React.ReactElement {
  return (
    <div
      style={{
        position: 'fixed',
        left: x,
        top: y,
        background: 'var(--bg-base)',
        border: '1px solid var(--border-control)',
        borderRadius: 'var(--radius-sm)',
        padding: 'var(--space-2)',
        boxShadow: 'var(--shadow-elevated)',
        pointerEvents: 'none',
        zIndex: 'var(--z-tooltip)' as unknown as number,
        fontFamily: 'var(--font-ui)',
      }}
    >
      <p style={{ fontSize: 'var(--text-xs)', fontWeight: 'var(--weight-semibold)', color: 'var(--text-primary)', margin: '0 0 4px 0' }}>
        {nome}
      </p>
      {taxa !== null ? (
        <p style={{ fontSize: 'var(--text-xs)', color: 'var(--text-secondary)', margin: 0 }}>
          {taxa.toLocaleString('pt-BR', { minimumFractionDigits: 1, maximumFractionDigits: 1 })}{' '}
          <span style={{ fontFamily: 'var(--font-mono)', color: 'var(--text-primary)' }}>notificações por 100 mil</span>
          {' · '}
          {ano}
        </p>
      ) : (
        <p style={{ fontSize: 'var(--text-xs)', color: 'var(--text-secondary)', margin: 0 }}>
          Sem dados disponíveis
        </p>
      )}
    </div>
  );
}

/**
 * Notification-rate choropleth with UF→município drill-down.
 *
 * Replicates the mortalidade map's national/municipal state machine but is
 * deliberately NOT a wrapper around that component — it is hardwired to the
 * SIM/SIH domain (its own indicador/filter data hooks) and would surface
 * "mortalidade"/"internações" labels. Reuses
 * ChoroplethLayer, Breadcrumb, Legend and lib/choropleth (CHORO_5,
 * getQuantileScale, NO_DATA_COLOR) verbatim — no new color scale.
 */
export function NotificationChoropleth(): React.ReactElement {
  const { uf, setUf, setMunicipio } = useVigilanciaFilterStore();
  const ufSummary = useNotificacoesUfSummary();
  const municipioSummary = useNotificacoesMunicipioSummary();

  const level: 'national' | 'municipal' = uf ? 'municipal' : 'national';
  const active = level === 'national' ? ufSummary : municipioSummary;
  const { rows, isLoading, isError } = active;

  const { byCode, latestAno } = useMemo(() => collapseToLatestAno(rows), [rows]);

  const geographyUrl = level === 'national' ? '/topojson/br-ufs.json' : `/topojson/uf/${uf}.json`;

  const [tooltipInfo, setTooltipInfo] = useState<TooltipInfo | null>(null);
  const [zoom, setZoom] = useState(DEFAULT_ZOOM);
  const [center, setCenter] = useState<[number, number]>(DEFAULT_CENTER);

  const mapContainerRef = React.useRef<HTMLDivElement>(null);
  const [dims, setDims] = React.useState({ width: 800, height: 400 });
  const [municipalProjConfig, setMunicipalProjConfig] = React.useState<{ scale: number; center: [number, number]; rotate: [number, number, number] } | null>(null);

  React.useEffect(() => {
    const el = mapContainerRef.current;
    if (!el) return;
    const ro = new ResizeObserver((entries) => {
      const { width, height } = entries[0].contentRect;
      if (width > 0 && height > 0) setDims({ width, height });
    });
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  React.useEffect(() => {
    if (!uf) { setMunicipalProjConfig(null); return; }
    let cancelled = false;
    fetch(`/topojson/uf/${uf}.json`)
      .then(r => r.json())
      .then((topology: Topology) => {
        if (cancelled) return;
        const objectName = Object.keys(topology.objects)[0];
        const geojson = feature(topology, topology.objects[objectName]) as FeatureCollection<Geometry>;
        const W = dims.width; const H = dims.height; const padding = 32;
        const proj = geoMercator().fitExtent([[padding, padding], [W - padding, H - padding]], geojson);
        const center = proj.invert!([W / 2, H / 2]) ?? [0, 0];
        setMunicipalProjConfig({ scale: proj.scale(), center: center as [number, number], rotate: [0, 0, 0] });
      })
      .catch(() => { if (!cancelled) setMunicipalProjConfig(null); });
    return () => { cancelled = true; };
  }, [uf, dims]);

  // Reset zoom/pan on every UF change (drill-down or drill-up), mirroring the mortalidade map's behavior.
  React.useEffect(() => {
    setZoom(DEFAULT_ZOOM);
    setCenter(DEFAULT_CENTER);
  }, [uf]);

  const handleSelect = useCallback(
    (code: string, _nome: string) => {
      void _nome;
      if (level === 'national') {
        setUf(code);
      } else {
        setMunicipio(code);
      }
    },
    [level, setUf, setMunicipio]
  );

  const handleHover = useCallback((info: TooltipInfo | null) => {
    setTooltipInfo(info);
  }, []);

  const handleHome = useCallback(() => {
    setUf('');
    setTooltipInfo(null);
  }, [setUf]);

  const { thresholds } = getQuantileScale(
    Array.from(byCode.values()).map((r) => r.taxa_por_100k),
    CHORO_5
  );

  if (isLoading) {
    return <LoadingState variant="skeleton-map" label="Carregando mapa de notificações..." />;
  }

  if (isError) return <FetchError />;
  if (rows.length === 0) return <EmptyState />;

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--space-2)' }}>
      <Breadcrumb sigla_uf={uf || undefined} onHome={handleHome} />

      {latestAno !== null && (
        <p style={{ fontFamily: 'var(--font-ui)', fontSize: 'var(--text-xs)', color: 'var(--text-muted)', margin: 0 }}>
          {`Taxa de notificação por 100 mil habitantes — ${latestAno}`}
        </p>
      )}

      <div
        ref={mapContainerRef}
        style={{
          position: 'relative',
          height: 400,
          background: 'var(--surface-card)',
        }}
        onMouseLeave={() => setTooltipInfo(null)}
      >
        <ComposableMap
          projection="geoMercator"
          projectionConfig={level === 'municipal' && municipalProjConfig ? municipalProjConfig : NATIONAL_PROJ}
          style={{ width: '100%', height: '100%', display: 'block' }}
          aria-hidden="true"
        >
          <ZoomableGroup
            zoom={zoom}
            center={level === 'municipal' && municipalProjConfig ? municipalProjConfig.center : center}
            onMoveEnd={({ coordinates, zoom: newZoom }) => {
              setZoom(newZoom);
              setCenter(coordinates);
            }}
          >
            <ChoroplethLayer
              geographyUrl={geographyUrl}
              byCode={byCode}
              level={level}
              onSelect={handleSelect}
              onHover={handleHover}
            />
          </ZoomableGroup>
        </ComposableMap>

        {tooltipInfo && <NotificationTooltip {...tooltipInfo} />}
      </div>

      {thresholds.length > 0 && (
        <Legend
          thresholds={thresholds}
          colors={CHORO_5}
          label="Taxa de notificação por 100 mil habitantes"
          unit="/ 100 mil hab."
        />
      )}
    </div>
  );
}
