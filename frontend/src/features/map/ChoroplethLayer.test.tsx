/**
 * ChoroplethLayer smoke test.
 *
 * Mocks react-simple-maps so jsdom can render the component without needing
 * a real SVG projection.  The mock makes Geographies call its render prop with
 * 3 synthetic geo objects, and Geography renders a <path> with the props passed.
 *
 * Asserts:
 * - All geo objects produce elements with className containing 'geo-path'
 * - Each element's style.fill is set from the quantile scale (not empty)
 * - No element's style has a 'hover' key (forbids the style-object API)
 */
import { describe, it, expect, vi } from 'vitest';
import { render } from '@testing-library/react';
import React from 'react';
import { ChoroplethLayer } from './ChoroplethLayer';
import { NO_DATA_COLOR } from '../../lib/choropleth';
import type { IndicadorResponse } from '../../types/api';

// ---------------------------------------------------------------------------
// Mock react-simple-maps — avoids SVG projection complexity in jsdom
// ---------------------------------------------------------------------------

const FAKE_GEOS = [
  { rsmKey: 'geo-0', id: '3550308', properties: { id: '3550308', name: 'São Paulo', sigla: 'SP' } },
  { rsmKey: 'geo-1', id: '3304557', properties: { id: '3304557', name: 'Rio de Janeiro', sigla: 'RJ' } },
  { rsmKey: 'geo-2', id: '1302603', properties: { id: '1302603', name: 'Manaus', sigla: 'AM' } },
];

vi.mock('react-simple-maps', () => ({
  Geographies: ({
    children,
  }: {
    geography: string;
    children: (arg: { geographies: typeof FAKE_GEOS }) => React.ReactNode;
  }) => <>{children({ geographies: FAKE_GEOS })}</>,

  Geography: ({
    className,
    style,
    'aria-label': ariaLabel,
    geography: _geography,
    ...rest
  }: {
    className?: string;
    style?: React.CSSProperties;
    'aria-label'?: string;
    geography?: unknown;
    [key: string]: unknown;
  }) => (
    <path
      className={className}
      style={style}
      aria-label={ariaLabel}
      data-testid="geography"
      {...(rest as object)}
    />
  ),
}));

// ---------------------------------------------------------------------------
// Test data
// ---------------------------------------------------------------------------

function makeRow(
  codigo_ibge: string,
  taxa: number | null,
  overrides?: Partial<IndicadorResponse>
): IndicadorResponse {
  return {
    sigla_uf: 'SP',
    codigo_ibge,
    nome_municipio: null,
    ano: 2022,
    total_eventos: 100,
    populacao: 1000000,
    taxa_por_100k: taxa,
    fonte: 'SIM',
    ...overrides,
  };
}

const BY_CODE = new Map<string, IndicadorResponse>([
  ['3550308', makeRow('3550308', 45.2)],
  ['3304557', makeRow('3304557', 30.1)],
  // geo-2 ('1302603') intentionally has NO entry → should get NO_DATA_COLOR
]);

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe('ChoroplethLayer (smoke)', () => {
  const defaultProps = {
    geographyUrl: '/topojson/uf/SP.json',
    byCode: BY_CODE,
    level: 'municipal' as const,
    onSelect: vi.fn(),
    onHover: vi.fn(),
  };

  it('renders one element per geo object in the mock Geographies', () => {
    const { getAllByTestId } = render(<ChoroplethLayer {...defaultProps} />);
    expect(getAllByTestId('geography')).toHaveLength(3);
  });

  it('each element has className containing geo-path', () => {
    const { getAllByTestId } = render(<ChoroplethLayer {...defaultProps} />);
    for (const el of getAllByTestId('geography')) {
      expect(el.className).toContain('geo-path');
    }
  });

  it('fill style is set from quantile scale (non-empty string) for data rows', () => {
    const { getAllByTestId } = render(<ChoroplethLayer {...defaultProps} />);
    const paths = getAllByTestId('geography');

    // Fill is a direct SVG presentation attribute, not an inline style.
    // geo-0 (3550308) has taxa 45.2 → fill should be a CHORO_5 color
    const fill0 = paths[0].getAttribute('fill');
    expect(fill0).toMatch(/^#[0-9A-Fa-f]{6}$/);
    expect(fill0).not.toBe(NO_DATA_COLOR);

    // geo-1 (3304557) has taxa 30.1 → also a valid color fill
    const fill1 = paths[1].getAttribute('fill');
    expect(fill1).toMatch(/^#[0-9A-Fa-f]{6}$/);
    expect(fill1).not.toBe(NO_DATA_COLOR);
  });

  it('geo with no data entry gets the NO_DATA_COLOR fill', () => {
    const { getAllByTestId } = render(<ChoroplethLayer {...defaultProps} />);
    const paths = getAllByTestId('geography');

    // geo-2 (1302603) is NOT in byCode → NO_DATA_COLOR
    expect(paths[2].getAttribute('fill')).toBe(NO_DATA_COLOR);
  });

  it('no element has a style object with a hover key (forbids style-object API)', () => {
    const { getAllByTestId } = render(<ChoroplethLayer {...defaultProps} />);
    for (const el of getAllByTestId('geography')) {
      // The style attribute is a CSSStyleDeclaration; check no 'hover' property is present.
      // This asserts the rerender-storm style-object API was NOT used.
      const style = (el as HTMLElement).style;
      // style.hover would be undefined / empty string on a CSSStyleDeclaration
      expect((style as unknown as Record<string, unknown>)['hover']).toBeUndefined();
    }
  });

  it('selected code receives className geo-path selected', () => {
    const { getAllByTestId } = render(
      <ChoroplethLayer {...defaultProps} selectedCode="3550308" />
    );
    const paths = getAllByTestId('geography');
    expect(paths[0].className).toBe('geo-path selected');
    expect(paths[1].className).toBe('geo-path');
    expect(paths[2].className).toBe('geo-path');
  });

  it('aria-label contains nome and taxa for data rows', () => {
    const { getAllByTestId } = render(<ChoroplethLayer {...defaultProps} />);
    const paths = getAllByTestId('geography');
    // geo-0: São Paulo with taxa 45.2
    expect(paths[0].getAttribute('aria-label')).toContain('São Paulo');
    expect(paths[0].getAttribute('aria-label')).toContain('100 mil habitantes');
  });

  it('aria-label for no-data row mentions "sem dados"', () => {
    const { getAllByTestId } = render(<ChoroplethLayer {...defaultProps} />);
    const paths = getAllByTestId('geography');
    // geo-2 has no data entry
    expect(paths[2].getAttribute('aria-label')).toContain('sem dados');
  });
});
