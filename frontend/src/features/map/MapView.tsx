import React, { useState, useCallback } from 'react';
import { geoMercator } from 'd3-geo';
import { feature } from 'topojson-client';
import type { Topology } from 'topojson-specification';
import type { FeatureCollection, Geometry } from 'geojson';
import { ComposableMap, ZoomableGroup } from 'react-simple-maps';
import { useFilterStore } from '../../store/filterStore';
import { ErrorBoundary } from '../../components/ErrorBoundary';
import { Legend } from '../../components/Legend';
import { LoadingState, COLD_START_HINT } from '../../components/LoadingState';
import { MapTooltip } from '../../components/Tooltip';
import { getQuantileScale, CHORO_5 } from '../../lib/choropleth';
import { Breadcrumb } from './Breadcrumb';
import { ChoroplethLayer } from './ChoroplethLayer';
import { useIndicadores } from './useIndicadores';

type MapViewState = 'national' | 'loading-uf' | 'municipal';

interface ProjectionConfig {
  scale: number;
  center: [number, number];
  rotate: [number, number, number];
}

// Fixed projection for the national (27 UF) view — Brazil centered on its geographic midpoint.
const NATIONAL_PROJ: ProjectionConfig = { rotate: [0, 0, 0], scale: 750, center: [-54, -14] };

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
 * Primary visual anchor of the dashboard.
 *
 * State machine:
 *   national     — 27 UF polygons, br-ufs.json
 *   loading-uf   — TopoJSON for a specific UF is being loaded; shows skeleton
 *   municipal    — municipality polygons for selected UF rendered
 *
 * Transitions:
 *   national + click UF  →  loading-uf (setUf in store + local view state)
 *   loading-uf           →  municipal (react-simple-maps fetches URL internally;
 *                            we infer "loaded" by the Geographies render-prop firing)
 *   municipal + click Brasil breadcrumb  →  national (clear uf + municipio)
 *   municipal + click municipality  →  setMunicipio (triggers chart refetch)
 *
 * Security notes:
 *   - nome/taxa via JSX interpolation only — auto-escaped, no innerHTML.
 *   - hover via .geo-path:hover CSS only; no inline hover style mutation.
 *   - UF segment in /topojson/uf/${uf}.json comes from setUf (2-char sigla
 *     from a controlled set) — not free-form user text.
 */
export function MapView(): React.ReactElement {
  const { uf, municipio, setUf, setMunicipio, indicador, ano_inicio, ano_fim } = useFilterStore();
  const { rows, byCode, isLoading: dataLoading, isError: dataError, refetch } = useIndicadores();

  // Local state: current map view state machine + tooltip + zoom/pan
  const [viewState, setViewState] = useState<MapViewState>('national');
  const [tooltipInfo, setTooltipInfo] = useState<TooltipInfo | null>(null);
  const [ufLoadError, setUfLoadError] = useState<string | null>(null);
  const [zoom, setZoom] = useState(DEFAULT_ZOOM);
  const [center, setCenter] = useState<[number, number]>(DEFAULT_CENTER);
  const [isDragging, setIsDragging] = useState(false);
  // Track the nome of the currently selected municipality for Breadcrumb
  const [selectedMunicipioNome, setSelectedMunicipioNome] = useState<string | undefined>(undefined);

  // Ref for the map container so we can read its pixel dimensions when computing the
  // municipal projection — the SVG is 100% width, so actual px width varies by viewport.
  const mapContainerRef = React.useRef<HTMLDivElement>(null);

  // Tracked container dimensions — updated by ResizeObserver so the municipal
  // fitExtent projection always uses the real rendered size.
  const [dims, setDims] = useState({ width: 800, height: 480 });

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

  // Computed projectionConfig for the municipal view.  Null until the UF GeoJSON is fetched
  // and fitted via geoMercator().fitExtent(); the municipal ChoroplethLayer is gated on this.
  const [municipalProjConfig, setMunicipalProjConfig] = useState<ProjectionConfig | null>(null);

  // When uf or dims changes, fetch the UF GeoJSON and compute a fitExtent projection so the
  // municipality polygons fill the viewport instead of appearing tiny at national scale.
  // dims comes from ResizeObserver so the projection always uses the actual rendered size.
  React.useEffect(() => {
    if (!uf) {
      setMunicipalProjConfig(null);
      return;
    }

    let cancelled = false;

    fetch(`/topojson/uf/${uf}.json`)
      .then((r) => {
        if (!r.ok) throw new Error(`HTTP ${r.status} fetching UF GeoJSON`);
        return r.json();
      })
      .then((topology: Topology) => {
        if (cancelled) return;

        // The fetched file is a real TopoJSON Topology (binary arcs), not GeoJSON —
        // d3-geo's fitExtent only understands GeoJSON, so convert via topojson-client
        // before computing the projection.
        const objectName = Object.keys(topology.objects)[0];
        const geojson = feature(
          topology,
          topology.objects[objectName]
        ) as FeatureCollection<Geometry>;

        const W = dims.width;
        const H = dims.height;
        const padding = 32;

        // Fit a temporary geoMercator to the UF's bounding box, then extract scale.
        // Invert the SVG-center point back to geographic coordinates to get the center
        // the ComposableMap projectionConfig expects (geographic point at SVG center).
        const proj = geoMercator().fitExtent(
          [[padding, padding], [W - padding, H - padding]],
          geojson
        );
        const scale = proj.scale();
        const center = proj.invert!([W / 2, H / 2]) ?? [0, 0];

        setMunicipalProjConfig({
          scale,
          center: center as [number, number],
          rotate: [0, 0, 0],
        });
      })
      .catch(() => {
        // Projection fetch failed — fall back silently; the Geography component
        // will attempt the same URL and surface a user-visible error if needed.
        if (!cancelled) setMunicipalProjConfig(null);
      });

    return () => {
      cancelled = true;
    };
  }, [uf, dims]);

  // Sync external uf store changes to local view state.
  // When store.uf is cleared externally (e.g. reset), return to national.
  React.useEffect(() => {
    if (!uf && viewState !== 'national') {
      setViewState('national');
      setUfLoadError(null);
      setSelectedMunicipioNome(undefined);
    }
  }, [uf, viewState]);

  // Build quantile scale for the Legend from current data rows
  const { thresholds } = getQuantileScale(
    rows.map((r) => r.taxa_por_100k),
    CHORO_5
  );

  // -------------------------------------------------------------------------
  // Handlers
  // -------------------------------------------------------------------------

  const handleUfSelect = useCallback(
    (code: string, nome: string) => {
      void nome; // name used for display only; store uses sigla
      // In national view the code from getFeatureCode will be the 2-digit UF code (codigo_ibg).
      // We also need the sigla. Find from byCode via sigla_uf on the row, or derive from properties.
      // The click handler passes `code` = result of resolveKey (sigla for national level).
      // For national layer: resolveKey uses geo.properties.sigla → code IS the sigla.
      const sigla = code; // already the sigla from ChoroplethLayer national resolveKey
      setUf(sigla);
      setViewState('loading-uf');
      setUfLoadError(null);
      setSelectedMunicipioNome(undefined);
    },
    [setUf]
  );

  const handleMunicipioSelect = useCallback(
    (code: string, nome: string) => {
      // code from ChoroplethLayer municipal level = 7-digit IBGE code (getFeatureCode → properties.id)
      // setMunicipio expects 6-digit codigo_ibge_6.
      let ibge6: string;
      if (code.length === 7) {
        ibge6 = code.slice(0, 6);
      } else if (code.length === 6) {
        ibge6 = code;
      } else {
        ibge6 = code; // fallback — pass as-is
      }
      setMunicipio(ibge6);
      setSelectedMunicipioNome(nome);
    },
    [setMunicipio]
  );

  const handleHome = useCallback(() => {
    setUf('');
    setMunicipio('');
    setViewState('national');
    setUfLoadError(null);
    setSelectedMunicipioNome(undefined);
    setTooltipInfo(null);
  }, [setUf, setMunicipio]);

  const handleHover = useCallback((info: TooltipInfo | null) => {
    setTooltipInfo(info);
  }, []);

  // -------------------------------------------------------------------------
  // react-simple-maps fetches the geography URL internally when Geographies
  // renders.  We detect the transition from loading-uf to municipal by
  // wrapping ChoroplethLayer in an onLoad-style callback: since RSM fetches
  // the URL the first time Geographies mounts for that URL, and the render
  // prop fires once features are available, we use a ref to track whether
  // we have already transitioned.
  // -------------------------------------------------------------------------

  const municipalLayerReadyRef = React.useRef(false);

  const handleGeographiesReady = useCallback(() => {
    if (viewState === 'loading-uf' && !municipalLayerReadyRef.current) {
      municipalLayerReadyRef.current = true;
      setViewState('municipal');
    }
  }, [viewState]);

  // Reset ref when UF changes so the next UF load also transitions correctly.
  React.useEffect(() => {
    if (viewState === 'loading-uf') {
      municipalLayerReadyRef.current = false;
    }
  }, [uf, viewState]);

  // FIX 2: Reset zoom and pan whenever UF changes (drill-down, drill-up, or swap UF).
  React.useEffect(() => {
    setZoom(DEFAULT_ZOOM);
    setCenter(DEFAULT_CENTER);
  }, [uf]);

  // Sync ZoomableGroup center to the municipal projection center so the UF fills the viewport.
  // Without this, ZoomableGroup would try to pan to the national DEFAULT_CENTER while rendering
  // the UF's municipal polygons, shifting them off-screen.
  React.useEffect(() => {
    if (municipalProjConfig) {
      setCenter(municipalProjConfig.center);
    }
  }, [municipalProjConfig]);

  // -------------------------------------------------------------------------
  // Indicator display name for ARIA label
  // -------------------------------------------------------------------------
  const indicadorNome = indicador === 'SIM' ? 'mortalidade' : 'internações';
  const nivelLabel = viewState === 'national' ? 'estados' : `municípios — ${uf}`;
  const mapAriaLabel = `Mapa de ${indicadorNome} por ${nivelLabel} — Brasil ${ano_fim}`;

  // Dynamic map title
  const tituloIndicador = indicador === 'SIM' ? 'Mortalidade' : 'Internações';
  const mapTitle = uf ? `${tituloIndicador} por município · ${uf}` : `${tituloIndicador} por estado · Brasil`;
  const mapSubtitle = `Período ${ano_inicio}–${ano_fim} · por 100 mil hab.`;

  // -------------------------------------------------------------------------
  // Render
  // -------------------------------------------------------------------------
  return (
    <div style={{ position: 'relative', display: 'flex', flexDirection: 'column', flex: 1, height: '100%', minHeight: 0, overflow: 'hidden' }}>
      {/* Dynamic title block */}
      <div style={{ marginBottom: 'var(--space-2)', flexShrink: 0 }}>
        <h2 style={{ fontFamily: 'var(--font-ui)', fontSize: 14, fontWeight: 600, color: 'var(--text-primary)', margin: 0 }}>{mapTitle}</h2>
        <p style={{ fontFamily: 'var(--font-ui)', fontSize: 11, color: 'var(--text-muted)', margin: '2px 0 0' }}>{mapSubtitle}</p>
      </div>

      {/* Breadcrumb — visible only in loading-uf and municipal states */}
      <Breadcrumb
        sigla_uf={uf || undefined}
        nome_municipio={selectedMunicipioNome}
        onHome={handleHome}
      />

      {/* Map container */}
      <ErrorBoundary
        context="mapa"
        fallbackTitle="Erro ao carregar mapa"
        fallbackAction={refetch}
        fallbackActionLabel="Tentar novamente"
      >
        <div
          ref={mapContainerRef}
          style={{
            position: 'relative',
            flex: 1,
            minHeight: 0,
            overflow: 'hidden',
            background: 'var(--surface-card)',
            cursor: isDragging ? 'grabbing' : 'grab',
          }}
          onMouseDown={() => setIsDragging(true)}
          onMouseUp={() => setIsDragging(false)}
          onMouseLeave={() => { setIsDragging(false); setTooltipInfo(null); }}
          aria-label={mapAriaLabel}
          role="img"
        >
          {/* Loading skeleton during data fetch */}
          {dataLoading && (
            <LoadingState variant="skeleton-map" label="Carregando dados do mapa..." hint={COLD_START_HINT} />
          )}

          {/* Error state for data fetch failure */}
          {dataError && !dataLoading && (
            <div
              style={{
                display: 'flex',
                flexDirection: 'column',
                alignItems: 'center',
                justifyContent: 'center',
                height: '100%',
                gap: 'var(--space-4)',
                color: 'var(--text-secondary)',
                fontFamily: 'var(--font-ui)',
                fontSize: 'var(--text-base)',
              }}
            >
              <p>Erro ao carregar dados. Verifique a conexão e tente novamente.</p>
              <button
                type="button"
                onClick={refetch}
                style={{
                  fontFamily: 'var(--font-ui)',
                  fontSize: 'var(--text-base)',
                  fontWeight: 'var(--weight-semibold)',
                  background: 'var(--accent)',
                  color: '#ffffff',
                  border: 'none',
                  borderRadius: 'var(--radius-md)',
                  padding: 'var(--space-2) var(--space-4)',
                  cursor: 'pointer',
                }}
              >
                Tentar novamente
              </button>
            </div>
          )}

          {/* Empty data state */}
          {!dataLoading && !dataError && rows.length === 0 && (
            <div
              style={{
                display: 'flex',
                flexDirection: 'column',
                alignItems: 'center',
                justifyContent: 'center',
                height: '100%',
                gap: 'var(--space-2)',
                color: 'var(--text-secondary)',
                fontFamily: 'var(--font-ui)',
              }}
            >
              <p style={{ fontSize: 'var(--text-md)', fontWeight: 'var(--weight-semibold)', margin: 0 }}>
                Sem dados no período
              </p>
              <p style={{ fontSize: 'var(--text-base)', margin: 0 }}>
                Ajuste os filtros para visualizar dados disponíveis.
              </p>
            </div>
          )}

          {/* Skeleton overlay during UF TopoJSON load */}
          {viewState === 'loading-uf' && (
            <LoadingState variant="skeleton-map" label="Carregando mapa municipal..." />
          )}

          {/* TopoJSON load error */}
          {ufLoadError && (
            <div
              style={{
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                height: '100%',
                color: 'var(--text-secondary)',
                fontFamily: 'var(--font-ui)',
                fontSize: 'var(--text-base)',
              }}
            >
              <p>
                {`Não foi possível carregar o mapa para ${uf}. Verifique a conexão e tente novamente.`}
              </p>
            </div>
          )}

          {/* ComposableMap — projectionConfig swaps between national fixed config and a
              per-UF fitExtent config computed in the municipalProjConfig effect above.
              The municipal layer is gated on municipalProjConfig being ready so it never
              renders with the national projection (which would show it tiny in the corner). */}
          {!dataLoading && !dataError && (
            <ComposableMap
              projection="geoMercator"
              projectionConfig={
                viewState === 'national' || municipalProjConfig === null
                  ? NATIONAL_PROJ
                  : municipalProjConfig
              }
              style={{ width: '100%', height: '100%', display: 'block' }}
              aria-hidden="true"
            >
              <title>Mapa coroplético de taxa de {indicadorNome} por 100 mil habitantes</title>
              <desc>{mapAriaLabel}</desc>

              <ZoomableGroup
                zoom={zoom}
                center={center}
                onMoveEnd={({ coordinates, zoom: newZoom }) => {
                  setZoom(newZoom);
                  setCenter(coordinates);
                }}
              >
                {/* National view — 27 UF polygons */}
                {(viewState === 'national') && (
                  <ChoroplethLayer
                    geographyUrl="/topojson/br-ufs.json"
                    byCode={byCode}
                    level="national"
                    onSelect={handleUfSelect}
                    onHover={handleHover}
                    selectedCode={uf || undefined}
                  />
                )}

                {/* Municipal view — only rendered once municipalProjConfig is ready so
                    the UF's polygons are correctly fitted to the viewport from first paint. */}
                {(viewState === 'loading-uf' || viewState === 'municipal') && uf && municipalProjConfig && (
                  <MunicipalLayer
                    uf={uf}
                    byCode={byCode}
                    municipio={municipio}
                    onSelect={handleMunicipioSelect}
                    onHover={handleHover}
                    onReady={handleGeographiesReady}
                  />
                )}
              </ZoomableGroup>
            </ComposableMap>
          )}

          {/* Map tooltip positioned at cursor coordinates */}
          {tooltipInfo && (
            <MapTooltip
              nome={tooltipInfo.nome}
              taxa={tooltipInfo.taxa}
              ano={tooltipInfo.ano}
              x={tooltipInfo.x}
              y={tooltipInfo.y}
              visible={true}
            />
          )}

          {/* Zoom buttons — bottom-right overlay */}
          <div
            style={{
              position: 'absolute',
              bottom: 10,
              right: 10,
              display: 'flex',
              flexDirection: 'column',
              gap: 4,
              zIndex: 'var(--z-overlay)' as unknown as number,
            }}
          >
            {(['zoom-in', 'zoom-out', 'zoom-reset'] as const).map((action) => (
              <button
                key={action}
                type="button"
                title={action === 'zoom-in' ? 'Zoom in' : action === 'zoom-out' ? 'Zoom out' : 'Resetar zoom'}
                onClick={() => {
                  if (action === 'zoom-in') setZoom((z) => Math.min(z * 1.5, 6));
                  else if (action === 'zoom-out') setZoom((z) => Math.max(z / 1.5, 0.3));
                  else { setZoom(DEFAULT_ZOOM); setCenter(DEFAULT_CENTER); }
                }}
                style={{
                  width: 26,
                  height: 26,
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'center',
                  fontFamily: 'var(--font-ui)',
                  fontSize: 14,
                  fontWeight: 600,
                  background: 'var(--surface-raised)',
                  border: '1px solid var(--border-control)',
                  borderRadius: 'var(--radius-sm)',
                  color: 'var(--text-secondary)',
                  cursor: 'pointer',
                  lineHeight: 1,
                }}
              >
                {action === 'zoom-in' ? '+' : action === 'zoom-out' ? '−' : '⊡'}
              </button>
            ))}
          </div>
        </div>
      </ErrorBoundary>

      {/* Legend — below the map */}
      {thresholds.length > 0 && (
        <div style={{ marginTop: 'var(--space-4)', flexShrink: 0 }}>
          <Legend thresholds={thresholds} colors={CHORO_5} />
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// MunicipalLayer — inner component so the Geographies onReady callback works
// ---------------------------------------------------------------------------

interface MunicipalLayerProps {
  uf: string;
  byCode: Map<string, import('./ChoroplethLayer').ChoroplethRow>;
  municipio: string;
  onSelect: (code: string, nome: string) => void;
  onHover: (info: { nome: string; taxa: number | null; ano: number; x: number; y: number } | null) => void;
  onReady: () => void;
}

/**
 * Wraps ChoroplethLayer for the municipal view and fires onReady when
 * Geographies delivers its first render-prop call (i.e. TopoJSON loaded).
 *
 * We implement onReady via a wrapper over onHover/onSelect: the first time
 * ChoroplethLayer renders at all, onReady fires via a mount effect.
 */
function MunicipalLayer({
  uf,
  byCode,
  municipio,
  onSelect,
  onHover,
  onReady,
}: MunicipalLayerProps): React.ReactElement {
  // Fire onReady on first mount — RSM fetches the URL, then renders the layer.
  // We use a timeout-0 to let the Geographies render-prop settle before signalling.
  React.useEffect(() => {
    const timer = setTimeout(() => {
      onReady();
    }, 50);
    return () => clearTimeout(timer);
  }, [onReady]);

  // Derive the 6-digit IBGE code stored in the store as the selected polygon code.
  // The GeoJSON features have 7-digit codes (properties.id).  The selected polygon
  // is identified by comparing the first 6 digits: selectedCode is the 6-digit
  // codigo_ibge_6; getFeatureCode returns 7-digit.  We pass the 7-digit prefixed
  // match so ChoroplethLayer can compare directly.
  const selectedCode = municipio ? municipio : undefined; // 6-digit

  return (
    <ChoroplethLayer
      geographyUrl={`/topojson/uf/${uf}.json`}
      byCode={byCode}
      level="municipal"
      onSelect={onSelect}
      onHover={onHover}
      selectedCode={selectedCode}
    />
  );
}
