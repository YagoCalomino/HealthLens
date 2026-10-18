import { render, screen, fireEvent } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { ErrorBoundary } from './ErrorBoundary';

// Component that throws on render when the prop is true
function Bomb({ shouldThrow }: { shouldThrow: boolean }): React.ReactElement {
  if (shouldThrow) {
    throw new Error('Test render error — internal path /src/secret.ts');
  }
  return <div>children rendered</div>;
}

// Suppress console.error for expected throws during tests
beforeEach(() => {
  vi.spyOn(console, 'error').mockImplementation(() => {});
});

describe('ErrorBoundary', () => {
  it('renders children when no error occurs', () => {
    render(
      <ErrorBoundary>
        <Bomb shouldThrow={false} />
      </ErrorBoundary>
    );
    expect(screen.getByText('children rendered')).toBeTruthy();
  });

  it('renders fallback UI when a child throws', () => {
    render(
      <ErrorBoundary>
        <Bomb shouldThrow={true} />
      </ErrorBoundary>
    );
    // Default fallback title should be visible
    expect(screen.getByText('Erro ao carregar dados')).toBeTruthy();
  });

  it('renders custom fallback title', () => {
    render(
      <ErrorBoundary fallbackTitle="Erro ao carregar mapa">
        <Bomb shouldThrow={true} />
      </ErrorBoundary>
    );
    expect(screen.getByText('Erro ao carregar mapa')).toBeTruthy();
  });

  it('shows default PT-BR error message — no stack trace, no internal paths', () => {
    render(
      <ErrorBoundary>
        <Bomb shouldThrow={true} />
      </ErrorBoundary>
    );
    // Default message must be present
    expect(screen.getByText(/Não foi possível carregar/)).toBeTruthy();
    // Internal error message must NOT be visible (security)
    expect(screen.queryByText(/Test render error/)).toBeNull();
    expect(screen.queryByText(/\/src\/secret/)).toBeNull();
  });

  it('renders retry button when fallbackAction is provided', () => {
    const onRetry = vi.fn();
    render(
      <ErrorBoundary fallbackAction={onRetry} fallbackActionLabel="Tentar novamente">
        <Bomb shouldThrow={true} />
      </ErrorBoundary>
    );
    const button = screen.getByRole('button', { name: 'Tentar novamente' });
    expect(button).toBeTruthy();
  });

  it('calls fallbackAction when retry button is clicked', () => {
    const onRetry = vi.fn();
    render(
      <ErrorBoundary fallbackAction={onRetry}>
        <Bomb shouldThrow={true} />
      </ErrorBoundary>
    );
    const button = screen.getByRole('button', { name: 'Tentar novamente' });
    fireEvent.click(button);
    expect(onRetry).toHaveBeenCalledTimes(1);
  });

  it('does not render retry button when fallbackAction is not provided', () => {
    render(
      <ErrorBoundary>
        <Bomb shouldThrow={true} />
      </ErrorBoundary>
    );
    expect(screen.queryByRole('button')).toBeNull();
  });

  it('uses getDerivedStateFromError lifecycle (class component pattern)', () => {
    // getDerivedStateFromError must be a static method — verify it exists
    expect(typeof ErrorBoundary.getDerivedStateFromError).toBe('function');
  });
});
