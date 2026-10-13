import React from 'react';

export interface LoadingStateProps {
  variant: 'skeleton-map' | 'skeleton-chart' | 'skeleton-table' | 'spinner';
  label?: string;
}

export function LoadingState({ variant, label = 'Carregando dados...' }: LoadingStateProps): React.ReactElement {
  return (
    <div role="status" aria-live="polite">
      <span className="sr-only">{label}</span>
      {variant === 'skeleton-map' && <SkeletonMap />}
      {variant === 'skeleton-chart' && <SkeletonChart />}
      {variant === 'skeleton-table' && <SkeletonTable />}
      {variant === 'spinner' && <Spinner />}
    </div>
  );
}

function SkeletonMap(): React.ReactElement {
  return (
    <div
      className="skeleton"
      style={{ width: '100%', height: '100%', minHeight: '480px' }}
      aria-hidden="true"
    />
  );
}

function SkeletonChart(): React.ReactElement {
  return (
    <div
      style={{ display: 'flex', flexDirection: 'column', gap: 'var(--space-2)' }}
      aria-hidden="true"
    >
      <div className="skeleton" style={{ width: '60%', height: '24px' }} />
      <div className="skeleton" style={{ width: '80%', height: '24px' }} />
      <div className="skeleton" style={{ width: '40%', height: '24px' }} />
    </div>
  );
}

function SkeletonTable(): React.ReactElement {
  return (
    <div
      style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}
      aria-hidden="true"
    >
      {[0, 1, 2, 3, 4].map((i) => (
        <div
          key={i}
          className="skeleton"
          style={{ width: '100%', height: '8px' }}
        />
      ))}
    </div>
  );
}

function Spinner(): React.ReactElement {
  return (
    <div
      style={{ display: 'flex', justifyContent: 'center', alignItems: 'center' }}
      aria-hidden="true"
    >
      <svg
        width="24"
        height="24"
        viewBox="0 0 24 24"
        fill="none"
        xmlns="http://www.w3.org/2000/svg"
        style={{ animation: 'spin 1s linear infinite' }}
      >
        <style>{`@keyframes spin { from { transform: rotate(0deg); } to { transform: rotate(360deg); } }`}</style>
        <circle
          cx="12"
          cy="12"
          r="10"
          stroke="var(--surface-control)"
          strokeWidth="3"
        />
        <path
          d="M12 2a10 10 0 0 1 10 10"
          stroke="var(--accent)"
          strokeWidth="3"
          strokeLinecap="round"
        />
      </svg>
    </div>
  );
}
