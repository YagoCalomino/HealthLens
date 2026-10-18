import React from 'react';

export interface ErrorBoundaryProps {
  children: React.ReactNode;
  fallbackTitle?: string;
  fallbackAction?: () => void;
  fallbackActionLabel?: string;
  context?: string;
}

interface ErrorBoundaryState {
  hasError: boolean;
}

// Warning triangle SVG — inline, no icon library dependency
function WarningTriangle(): React.ReactElement {
  return (
    <svg
      width="20"
      height="20"
      viewBox="0 0 24 24"
      fill="none"
      xmlns="http://www.w3.org/2000/svg"
      aria-hidden="true"
      style={{ color: 'var(--status-alert)', flexShrink: 0 }}
    >
      <path
        d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"
        stroke="var(--status-alert)"
        strokeWidth="2"
        strokeLinecap="round"
        strokeLinejoin="round"
        fill="none"
      />
      <line
        x1="12"
        y1="9"
        x2="12"
        y2="13"
        stroke="var(--status-alert)"
        strokeWidth="2"
        strokeLinecap="round"
      />
      <line
        x1="12"
        y1="17"
        x2="12.01"
        y2="17"
        stroke="var(--status-alert)"
        strokeWidth="2"
        strokeLinecap="round"
      />
    </svg>
  );
}

const DEFAULT_MESSAGE =
  'Não foi possível carregar os dados. Tente novamente ou ajuste os filtros.';

export class ErrorBoundary extends React.Component<ErrorBoundaryProps, ErrorBoundaryState> {
  static defaultProps = {
    fallbackTitle: 'Erro ao carregar dados',
    fallbackActionLabel: 'Tentar novamente',
  };

  constructor(props: ErrorBoundaryProps) {
    super(props);
    this.state = { hasError: false };
  }

  static getDerivedStateFromError(_error: Error): ErrorBoundaryState {
    return { hasError: true };
  }

  componentDidCatch(error: Error, info: React.ErrorInfo): void {
    // Log to console only — NEVER render error.message or stack to the user
    console.error('[ErrorBoundary] Render error caught:', error, info.componentStack);
  }

  handleRetry = (): void => {
    this.setState({ hasError: false });
    this.props.fallbackAction?.();
  };

  render(): React.ReactNode {
    if (!this.state.hasError) {
      return this.props.children;
    }

    const {
      fallbackTitle = 'Erro ao carregar dados',
      fallbackAction,
      fallbackActionLabel = 'Tentar novamente',
    } = this.props;

    return (
      <div
        style={{
          background: 'var(--surface-card)',
          border: '1px solid var(--border-control)',
          borderLeft: '4px solid var(--status-alert)',
          borderRadius: 'var(--radius-md)',
          boxShadow: 'var(--shadow-card)',
          padding: 'var(--space-4) var(--space-6)',
        }}
      >
        <div style={{ display: 'flex', alignItems: 'flex-start', gap: 'var(--space-2)' }}>
          <WarningTriangle />
          <div style={{ flex: 1 }}>
            <h2
              style={{
                fontFamily: 'var(--font-ui)',
                fontSize: 'var(--text-md)',
                fontWeight: 'var(--weight-semibold)',
                color: 'var(--text-primary)',
                margin: '0 0 var(--space-2) 0',
              }}
            >
              {fallbackTitle}
            </h2>
            <p
              style={{
                fontFamily: 'var(--font-ui)',
                fontSize: 'var(--text-base)',
                fontWeight: 'var(--weight-regular)',
                color: 'var(--text-secondary)',
                margin: fallbackAction ? '0 0 var(--space-4) 0' : '0',
              }}
            >
              {DEFAULT_MESSAGE}
            </p>
            {fallbackAction && (
              <button
                onClick={this.handleRetry}
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
                {fallbackActionLabel}
              </button>
            )}
          </div>
        </div>
      </div>
    );
  }
}
