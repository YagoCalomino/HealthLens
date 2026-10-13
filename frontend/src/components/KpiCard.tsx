import React from 'react';

// ---------------------------------------------------------------------------
// KpiCard — extracted from KpiStrip.tsx's inline, non-exported KpiCard so it
// can be reused by MultiAgravoCard.tsx without duplicating the style
// block. Moved verbatim except for one correction: the value's font size uses
// var(--text-xl) (22px), not the hardcoded 24px literal KpiStrip.tsx's inline
// copy carries — that drift must not be propagated into new code.
// ---------------------------------------------------------------------------

export interface KpiCardProps {
  label: string;
  value: string;
  delta?: string;
  deltaColor?: string;
  isForecast?: boolean;
  /** Optional accent colour for the value text (e.g. agravo identity colour). */
  accentColor?: string;
}

export function KpiCard({ label, value, delta, deltaColor, isForecast, accentColor }: KpiCardProps): React.ReactElement {
  return (
    <div style={{
      background: isForecast ? 'linear-gradient(160deg, #1a1530, #12101d)' : 'var(--surface-card)',
      border: isForecast ? '1px solid rgba(149,128,255,.25)' : '1px solid var(--border-subtle)',
      borderRadius: 'var(--radius-lg)',
      padding: '14px 16px',
      flex: 1,
      minWidth: 0,
    }}>
      <div style={{ fontFamily: 'var(--font-ui)', fontSize: 11, color: isForecast ? 'var(--forecast)' : 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '.5px', marginBottom: 6 }}>
        {label}
      </div>
      <div style={{ fontFamily: 'var(--font-mono)', fontSize: 'var(--text-xl)', fontWeight: 600, color: accentColor ?? (isForecast ? 'var(--forecast)' : 'var(--text-primary)'), lineHeight: 1.1 }}>
        {value}
      </div>
      {delta !== undefined && (
        <div style={{ fontFamily: 'var(--font-mono)', fontSize: 12, color: deltaColor ?? 'var(--text-secondary)', marginTop: 4 }}>
          {delta}
        </div>
      )}
    </div>
  );
}
