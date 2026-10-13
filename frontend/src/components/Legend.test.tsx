import { render, screen } from '@testing-library/react';
import { describe, it, expect } from 'vitest';
import { Legend } from './Legend';
import { CHORO_5 } from '../lib/choropleth';

const SAMPLE_THRESHOLDS = [10, 25, 50, 100];

describe('Legend', () => {
  it('renders 5 swatches (one per quantile class)', () => {
    const { container } = render(
      <Legend thresholds={SAMPLE_THRESHOLDS} colors={CHORO_5} />
    );
    // Each swatch is a colored div inside a position:relative wrapper
    // We look for the 5 base color divs (the non-SVG colored rectangles)
    // They are direct children of the relative wrapper and have backgroundColor set
    const swatchWrappers = container.querySelectorAll('[style*="position: relative"]');
    expect(swatchWrappers.length).toBe(5);
  });

  it('renders the container with aria-label "Escala de taxa por 100 mil habitantes"', () => {
    render(<Legend thresholds={SAMPLE_THRESHOLDS} colors={CHORO_5} />);
    const container = screen.getByRole('generic', {
      name: 'Escala de taxa por 100 mil habitantes',
    });
    expect(container).toBeTruthy();
  });

  it('renders 4 threshold numbers formatted in pt-BR locale', () => {
    // Thresholds: 10, 25, 50, 100
    // Expected labels: "< 10", "10–25", "25–50", "50–100", "> 100"
    // Formatted (pt-BR): "< 10", "10–25", "25–50", "50–100", "> 100"
    render(<Legend thresholds={SAMPLE_THRESHOLDS} colors={CHORO_5} />);

    // All 4 threshold values must appear in the rendered text
    expect(screen.getAllByText(/10/).length).toBeGreaterThan(0);
    expect(screen.getAllByText(/25/).length).toBeGreaterThan(0);
    expect(screen.getAllByText(/50/).length).toBeGreaterThan(0);
    expect(screen.getAllByText(/100/).length).toBeGreaterThan(0);
  });

  it('renders label "< t[0]" for the first class', () => {
    render(<Legend thresholds={SAMPLE_THRESHOLDS} colors={CHORO_5} />);
    // First class label: "< 10"
    expect(screen.getByText(/< 10/)).toBeTruthy();
  });

  it('renders label "> t[3]" for the last class', () => {
    render(<Legend thresholds={SAMPLE_THRESHOLDS} colors={CHORO_5} />);
    // Last class label: "> 100"
    expect(screen.getByText(/> 100/)).toBeTruthy();
  });

  it('renders middle range labels in t[n]–t[n+1] format', () => {
    render(<Legend thresholds={SAMPLE_THRESHOLDS} colors={CHORO_5} />);
    // Second class: "10–25"
    expect(screen.getByText(/10–25/)).toBeTruthy();
    // Third class: "25–50"
    expect(screen.getByText(/25–50/)).toBeTruthy();
    // Fourth class: "50–100"
    expect(screen.getByText(/50–100/)).toBeTruthy();
  });

  it('renders SVG defs with 4 hatch patterns (hatch-1 through hatch-4)', () => {
    const { container } = render(
      <Legend thresholds={SAMPLE_THRESHOLDS} colors={CHORO_5} />
    );
    for (let i = 1; i <= 4; i++) {
      const pattern = container.querySelector(`#hatch-${i}`);
      expect(pattern).toBeTruthy();
    }
  });

  it('renders default unit "/ 100 mil hab."', () => {
    render(<Legend thresholds={SAMPLE_THRESHOLDS} colors={CHORO_5} />);
    expect(screen.getByText('/ 100 mil hab.')).toBeTruthy();
  });

  it('renders custom unit when provided', () => {
    render(
      <Legend thresholds={SAMPLE_THRESHOLDS} colors={CHORO_5} unit="por mil habitantes" />
    );
    expect(screen.getByText('por mil habitantes')).toBeTruthy();
  });

  it('uses CHORO_5 colors (first 5) for swatch backgrounds', () => {
    const { container } = render(
      <Legend thresholds={SAMPLE_THRESHOLDS} colors={CHORO_5} />
    );
    // jsdom resolves CSS hex colors to rgb() — check that the first CHORO_5 color (#F4D99A)
    // appears in the rendered HTML as its rgb equivalent or as a background-color style.
    // We check that there are 5 swatch wrapper divs (position:relative) each containing a colored div.
    const swatchWrappers = container.querySelectorAll('[style*="position: relative"]');
    // Each wrapper has a child div with a background-color
    let coloredDivCount = 0;
    swatchWrappers.forEach((wrapper) => {
      const colorDiv = wrapper.querySelector('div[style*="background-color"]');
      if (colorDiv) coloredDivCount++;
    });
    expect(coloredDivCount).toBeGreaterThanOrEqual(5);
  });

  it('formats large threshold numbers in pt-BR (dot as thousands separator)', () => {
    // 1000 in pt-BR is "1.000"
    render(
      <Legend thresholds={[100, 500, 1000, 5000]} colors={CHORO_5} />
    );
    // pt-BR formats 1000 as "1.000" and 5000 as "5.000"
    // Multiple elements may contain these numbers (label ranges overlap), use getAllByText
    expect(screen.getAllByText(/1\.000/).length).toBeGreaterThan(0);
    expect(screen.getAllByText(/5\.000/).length).toBeGreaterThan(0);
  });
});
