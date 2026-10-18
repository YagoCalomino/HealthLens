/**
 * Geo file format and IBGE code field discovery.
 *
 * `frontend/public/topojson/*.json` are real binary-arc TopoJSON `Topology` objects
 * (converted from the original GeoJSON sourcing via `mapshaper`,
 * commit b0200a4). Each file has a single top-level object under
 * `topology.objects` (`br-ufs` for the national file, the UF sigla — e.g. `SP` — for
 * per-UF municipality files) holding a `GeometryCollection`; per-feature properties were
 * preserved unchanged by the conversion, so the field names documented below are still
 * accurate.
 *
 * Two independent consumers exist for these files:
 *   - `ChoroplethLayer.tsx` passes the URL to react-simple-maps' `<Geographies
 *     geography={url}>`, which fetches and auto-converts the Topology internally via its
 *     own bundled `topojson-client` — no manual conversion needed on that path.
 *   - `MapView.tsx` independently fetches the UF file to compute a `fitExtent` projection
 *     via `d3-geo`, which only understands GeoJSON — that path MUST convert the fetched
 *     Topology to GeoJSON via `topojson-client`'s `feature()` before calling `fitExtent`
 *     (fixed after a regression where the raw Topology silently produced a degenerate
 *     `scale: -0` / `center: NaN` projection with no thrown error).
 *
 * Property discovery (inspected files: frontend/public/topojson/br-ufs.json and
 * frontend/public/topojson/uf/SP.json):
 *   - br-ufs.json features:    properties.codigo_ibg (2-digit UF IBGE code, e.g. "35"),
 *                               properties.sigla ("SP"), properties.name ("São Paulo")
 *   - uf/{SIGLA}.json features: properties.id (7-digit municipality IBGE code, e.g.
 *                               "3550308" for São Paulo capital — matches
 *                               dim_local.codigo_ibge_7), properties.name
 *
 * There is no single property name shared by both files (national file has no 7-digit
 * municipality code; per-UF files have no 2-digit UF code under the same key as the
 * national file), so TOPO_ID_FIELD documents the per-UF (municipality-level) field,
 * which is what the choropleth join actually needs — the national view joins
 * on TOPO_UF_FIELD instead.
 */

/** Property holding the 7-digit municipality IBGE code in uf/{SIGLA}.json features. */
export const TOPO_ID_FIELD = 'id';

/** Property holding the UF sigla in br-ufs.json features (e.g. "SP", "RJ"). */
export const TOPO_UF_FIELD = 'sigla';

/** Property holding the 2-digit UF IBGE code in br-ufs.json features (e.g. "35"). */
export const TOPO_UF_CODE_FIELD = 'codigo_ibg';

/** Property holding the human-readable name in both br-ufs.json and uf/{SIGLA}.json. */
export const TOPO_NAME_FIELD = 'name';

/**
 * Minimal shape of the object react-simple-maps passes to each render-prop callback
 * inside `<Geographies>` — a GeoJSON Feature with optional top-level `id`.
 */
interface GeoFeatureLike {
  id?: string | number;
  properties?: Record<string, unknown>;
}

/**
 * Reads the IBGE code from a react-simple-maps geography object.
 *
 * Checks `properties[TOPO_ID_FIELD]` first (municipality files), falling back to
 * `properties[TOPO_UF_CODE_FIELD]` (national UF file) and finally `geo.id` if neither
 * property is present. Always returns a string so callers can compare directly against
 * API `codigo_ibge_7` / `codigo_uf` string fields without type coercion surprises.
 */
export function getFeatureCode(geo: GeoFeatureLike): string {
  const props = geo.properties ?? {};
  const value = props[TOPO_ID_FIELD] ?? props[TOPO_UF_CODE_FIELD] ?? geo.id;
  return value === undefined || value === null ? '' : String(value);
}
