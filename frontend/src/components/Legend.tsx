import React from 'react';

export interface LegendProps {
  thresholds: number[];
  colors: readonly string[];
  unit?: string;
  label?: string;
}

// SVG hatch pattern IDs — defined in <defs> and overlaid on swatches for color-blind accessibility.
// Same pattern IDs are referenced by map polygon fills.
const HATCH_PATTERNS = [
  // hatch-1: 15% density diagonal
  <pattern key="hatch-1" id="hatch-1" patternUnits="userSpaceOnUse" width="6" height="6">
    <line x1="0" y1="6" x2="6" y2="0" stroke="currentColor" strokeWidth="0.8" opacity="0.15" />
  </pattern>,
  // hatch-2: 30% density diagonal
  <pattern key="hatch-2" id="hatch-2" patternUnits="userSpaceOnUse" width="6" height="6">
    <line x1="0" y1="6" x2="6" y2="0" stroke="currentColor" strokeWidth="0.8" opacity="0.30" />
  </pattern>,
  // hatch-3: 50% density diagonal
  <pattern key="hatch-3" id="hatch-3" patternUnits="userSpaceOnUse" width="6" height="6">
    <line x1="0" y1="6" x2="6" y2="0" stroke="currentColor" strokeWidth="0.8" opacity="0.50" />
  </pattern>,
  // hatch-4: 70% density diagonal (dense)
  <pattern key="hatch-4" id="hatch-4" patternUnits="userSpaceOnUse" width="6" height="6">
    <line x1="0" y1="6" x2="6" y2="0" stroke="currentColor" strokeWidth="0.8" opacity="0.70" />
  </pattern>,
];

function formatThreshold(value: number): string {
  // Use enough decimal places so tiny values (e.g. 0.15 from sample data) are readable.
  // Values ≥ 1: integer format (matches typical "per 100k" rates like 14, 26).
  // Values < 1: up to 2 decimal places ("0,15" instead of degenerate "0").
  if (value < 1) {
    return value.toLocaleString('pt-BR', { minimumFractionDigits: 1, maximumFractionDigits: 2 });
  }
  return value.toLocaleString('pt-BR', { maximumFractionDigits: 0 });
}

// Derive the 5 label strings from 4 threshold values.
// Label format: "< t[0]", "t[0]–t[1]", "t[1]–t[2]", "t[2]–t[3]", "> t[3]"
function buildLabels(thresholds: number[]): string[] {
  if (thresholds.length < 4) {
    // Degenerate case: not enough thresholds — return 5 empty labels
    return ['', '', '', '', ''];
  }
  const [t0, t1, t2, t3] = thresholds;
  return [
    `< ${formatThreshold(t0)}`,
    `${formatThreshold(t0)}–${formatThreshold(t1)}`,
    `${formatThreshold(t1)}–${formatThreshold(t2)}`,
    `${formatThreshold(t2)}–${formatThreshold(t3)}`,
    `> ${formatThreshold(t3)}`,
  ];
}

// hatch overlay URL for each quantile class (class 0 has no hatch)
function hatchUrl(classIndex: number): string | undefined {
  if (classIndex === 0) return undefined;
  return `url(#hatch-${classIndex})`;
}

export function Legend({
  thresholds,
  colors,
  unit = '/ 100 mil hab.',
  label = 'Taxa por 100 mil habitantes',
}: LegendProps): React.ReactElement {
  const labels = buildLabels(thresholds);

  return (
    <div
      aria-label="Escala de taxa por 100 mil habitantes"
      style={{
        display: 'flex',
        flexDirection: 'column',
        gap: 'var(--space-1)',
      }}
    >
      {/* Hidden SVG with hatch pattern definitions — referenced by swatches */}
      <svg width="0" height="0" aria-hidden="true" style={{ position: 'absolute' }}>
        <defs>{HATCH_PATTERNS}</defs>
      </svg>

      <p
        style={{
          fontFamily: 'var(--font-ui)',
          fontSize: 'var(--text-xs)',
          color: 'var(--text-secondary)',
          margin: '0 0 var(--space-1) 0',
        }}
      >
        {label}
      </p>

      <div
        style={{
          display: 'flex',
          flexDirection: 'row',
          flexWrap: 'wrap',
          gap: 'var(--space-2)',
          alignItems: 'center',
        }}
      >
        {colors.slice(0, 5).map((color, index) => (
          <div
            key={index}
            style={{
              display: 'flex',
              alignItems: 'center',
              gap: 'var(--space-1)',
            }}
          >
            {/* Swatch: base color rectangle + optional hatch SVG overlay */}
            <div style={{ position: 'relative', width: '16px', height: '16px', flexShrink: 0 }}>
              <div
                style={{
                  width: '16px',
                  height: '16px',
                  backgroundColor: color,
                  borderRadius: 'var(--radius-sm)',
                }}
              />
              {hatchUrl(index) && (
                <svg
                  aria-hidden="true"
                  style={{
                    position: 'absolute',
                    top: 0,
                    left: 0,
                    width: '16px',
                    height: '16px',
                    borderRadius: 'var(--radius-sm)',
                  }}
                  viewBox="0 0 16 16"
                >
                  <rect
                    width="16"
                    height="16"
                    fill={hatchUrl(index)}
                    rx="4"
                  />
                </svg>
              )}
            </div>

            {/* Threshold label in Fira Code */}
            <span
              style={{
                fontFamily: 'var(--font-mono)',
                fontSize: 'var(--text-xs)',
                fontWeight: 'var(--weight-regular)',
                color: 'var(--text-secondary)',
                whiteSpace: 'nowrap',
              }}
            >
              {labels[index]}
            </span>
          </div>
        ))}
      </div>

      <p
        style={{
          fontFamily: 'var(--font-mono)',
          fontSize: 'var(--text-xs)',
          color: 'var(--text-secondary)',
          margin: 'var(--space-1) 0 0 0',
        }}
      >
        {unit}
      </p>
    </div>
  );
}
