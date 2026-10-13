import React, { useMemo } from 'react';
import { Geographies, Geography } from 'react-simple-maps';
import { getQuantileScale, NO_DATA_COLOR, CHORO_5 } from '../../lib/choropleth';
import { getFeatureCode, TOPO_NAME_FIELD, TOPO_UF_FIELD } from '../../lib/topojson';

/**
 * Minimal row shape ChoroplethLayer actually reads — the two fields used by
 * getTaxa/getAno below. IndicadorResponse and NotificacaoSummaryResponse both
 * satisfy this structurally, so callers from either domain (mortalidade/SIH
 * or SINAN notificações) can share this component without any change here.
 */
export interface ChoroplethRow {
  taxa_por_100k: number | null;
  ano: number;
}

export interface ChoroplethLayerProps {
  /** URL to the GeoJSON FeatureCollection (br-ufs.json or uf/{UF}.json). */
  geographyUrl: string;
  /** byCode map from useIndicadores (or an equivalent per-domain hook) — keyed by 7-digit IBGE code or sigla_uf. */
  byCode: Map<string, ChoroplethRow>;
  level: 'national' | 'municipal';
  /** Called when user clicks a polygon; receives the IBGE code and display name. */
  onSelect: (code: string, nome: string) => void;
  /** Called on hover with tooltip data (or null to hide tooltip). */
  onHover: (
    info: { nome: string; taxa: number | null; ano: number; x: number; y: number } | null
  ) => void;
  /** Currently selected polygon code — renders .geo-path.selected when matched. */
  selectedCode?: string;
}

/**
 * Renders a react-simple-maps Geographies layer with quantile-encoded choropleth fill.
 *
 * Security notes:
 * - nome and taxa are rendered via aria-label string attribute and JSX text — auto-escaped.
 * - Hover visual feedback is handled by the .geo-path:hover CSS rule only (index.css).
 *   The style object's `hover` key is NEVER used — that pattern triggers a rerender storm.
 * - Fill is set ONCE at mount via inline style={{ fill }}.  Hover does NOT mutate inline style.
 *
 * TopoJSON / GeoJSON join logic:
 * - National level: geo.properties.sigla (TOPO_UF_FIELD) used as lookup key in byCode.
 * - Municipal level: getFeatureCode(geo) returns 7-digit IBGE code from properties.id.
 */
export function ChoroplethLayer({
  geographyUrl,
  byCode,
  level,
  onSelect,
  onHover,
  selectedCode,
}: ChoroplethLayerProps): React.ReactElement {
  // Build quantile scale once per byCode snapshot — thresholds recalculate on every filter change.
  const { color: colorFn, thresholds } = useMemo(() => {
    const taxaValues = Array.from(byCode.values()).map((r) => r.taxa_por_100k);
    return getQuantileScale(taxaValues, CHORO_5);
  }, [byCode]);

  // Expose thresholds for Legend via a data attribute on the wrapper — caller can read if needed.
  void thresholds; // used via closure in colorFn

  function getTaxa(geo: { id?: string | number; properties?: Record<string, unknown> }): number | null {
    const lookupKey = resolveKey(geo, level);
    const row = byCode.get(lookupKey);
    return row?.taxa_por_100k ?? null;
  }

  function getName(geo: { id?: string | number; properties?: Record<string, unknown> }): string {
    const props = geo.properties ?? {};
    return String(props[TOPO_NAME_FIELD] ?? props[TOPO_UF_FIELD] ?? getFeatureCode(geo) ?? '');
  }

  function getAno(geo: { id?: string | number; properties?: Record<string, unknown> }): number {
    const lookupKey = resolveKey(geo, level);
    const row = byCode.get(lookupKey);
    return row?.ano ?? new Date().getFullYear();
  }

  function resolveKey(
    geo: { id?: string | number; properties?: Record<string, unknown> },
    lv: 'national' | 'municipal'
  ): string {
    if (lv === 'national') {
      // National file: join on sigla_uf (properties.sigla, e.g. "SP")
      const props = geo.properties ?? {};
      const sigla = props[TOPO_UF_FIELD];
      if (sigla) return String(sigla);
    }
    // Municipal file: join on 7-digit IBGE code (properties.id)
    return getFeatureCode(geo);
  }

  return (
    <Geographies geography={geographyUrl}>
      {({ geographies }) =>
        geographies.map((geo) => {
          const taxa = getTaxa(geo);
          const fill = taxa !== null ? colorFn(taxa) : NO_DATA_COLOR;
          const nome = getName(geo);
          const lookupKey = resolveKey(geo, level);
          // Municipal lookupKey is 7-digit; selectedCode is 6-digit codigo_ibge_6.
          // Slice to selectedCode.length handles both national (sigla match) and municipal (prefix match).
          const isSelected =
            selectedCode !== undefined &&
            lookupKey.slice(0, selectedCode.length) === selectedCode;

          // Accessible label read by screen readers
          const ariaLabel =
            taxa !== null
              ? `${nome}: ${taxa.toLocaleString('pt-BR', { minimumFractionDigits: 1, maximumFractionDigits: 1 })} por 100 mil habitantes`
              : `${nome}: sem dados disponíveis`;

          // Conditional stroke: selected polygon → lavender contour; otherwise level-dependent subtle borders.
          const strokeColor = isSelected ? '#CDD8FF' : (level === 'national' ? 'rgba(11,14,20,.85)' : 'rgba(8,12,18,.55)');
          const strokeWidth = isSelected ? 2 : (level === 'national' ? 0.9 : 0.4);

          return (
            <Geography
              key={geo.rsmKey}
              geography={geo}
              className={isSelected ? 'geo-path selected' : 'geo-path'}
              // RSM v3 Geography forwards all extra props to the underlying <path>.
              // Use fill as a direct SVG presentation attribute — avoids the stale
              // @types/react-simple-maps `style` type (v2 API shape) and any RSM
              // style-object processing. Hover effect is CSS-only.
              // eslint-disable-next-line @typescript-eslint/no-explicit-any
              fill={fill}
              stroke={strokeColor}
              strokeWidth={strokeWidth}
              aria-label={ariaLabel}
              onMouseEnter={(evt: React.MouseEvent) => {
                onHover({
                  nome,
                  taxa,
                  ano: getAno(geo),
                  x: evt.clientX,
                  y: evt.clientY,
                });
              }}
              onMouseMove={(evt: React.MouseEvent) => {
                onHover({
                  nome,
                  taxa,
                  ano: getAno(geo),
                  x: evt.clientX,
                  y: evt.clientY,
                });
              }}
              onMouseLeave={() => {
                onHover(null);
              }}
              onClick={() => {
                onSelect(lookupKey, nome);
              }}
            />
          );
        })
      }
    </Geographies>
  );
}
