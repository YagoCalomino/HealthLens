import { render, screen } from '@testing-library/react';
import { describe, it, expect } from 'vitest';
import { LoadingState } from './LoadingState';

describe('LoadingState', () => {
  it('renders with role="status" and aria-live="polite"', () => {
    const { container } = render(<LoadingState variant="spinner" />);
    const wrapper = container.firstChild as HTMLElement;
    expect(wrapper.getAttribute('role')).toBe('status');
    expect(wrapper.getAttribute('aria-live')).toBe('polite');
  });

  it('renders default screen reader label "Carregando dados..."', () => {
    render(<LoadingState variant="spinner" />);
    expect(screen.getByText('Carregando dados...')).toBeTruthy();
  });

  it('renders custom label when provided', () => {
    render(<LoadingState variant="spinner" label="Aguardando mapa..." />);
    expect(screen.getByText('Aguardando mapa...')).toBeTruthy();
  });

  it('renders skeleton-map variant', () => {
    const { container } = render(<LoadingState variant="skeleton-map" />);
    // The map skeleton is a div with the .skeleton class
    const skeleton = container.querySelector('.skeleton');
    expect(skeleton).toBeTruthy();
  });

  it('renders skeleton-chart variant with 3 bars', () => {
    const { container } = render(<LoadingState variant="skeleton-chart" />);
    const bars = container.querySelectorAll('.skeleton');
    expect(bars.length).toBe(3);
  });

  it('renders skeleton-table variant with 5 rows', () => {
    const { container } = render(<LoadingState variant="skeleton-table" />);
    const rows = container.querySelectorAll('.skeleton');
    expect(rows.length).toBe(5);
  });

  it('renders visible hint when provided', () => {
    render(<LoadingState variant="skeleton-map" hint="Waking up..." />);
    expect(screen.getByText('Waking up...')).toBeTruthy();
  });

  it('renders spinner variant with SVG', () => {
    const { container } = render(<LoadingState variant="spinner" />);
    const svg = container.querySelector('svg');
    expect(svg).toBeTruthy();
  });
});
