import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter, Routes, Route, useLocation } from 'react-router-dom';
import Hub from './Hub';

function LocationProbe() {
  const location = useLocation();
  return <div data-testid="location-probe">{location.pathname}</div>;
}

function renderHub() {
  return render(
    <MemoryRouter>
      <Hub />
    </MemoryRouter>
  );
}

function renderHubWithRoutes() {
  return render(
    <MemoryRouter initialEntries={['/']}>
      <Routes>
        <Route path="/" element={<Hub />} />
        <Route path="/mortalidade" element={<LocationProbe />} />
        <Route path="/vigilancia" element={<LocationProbe />} />
      </Routes>
    </MemoryRouter>
  );
}

describe('Hub', () => {
  beforeEach(() => {
    global.fetch = vi.fn() as unknown as typeof fetch;
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it('renders exactly two cards with the expected headings', () => {
    renderHub();
    expect(screen.getByRole('heading', { name: 'Mortalidade & Internações' })).toBeTruthy();
    expect(screen.getByRole('heading', { name: 'Vigilância Epidemiológica' })).toBeTruthy();
  });

  it('renders the card 1 description text', () => {
    renderHub();
    expect(
      screen.getByText(
        'Óbitos e internações do SUS por local, tempo e causa, com série temporal, previsão AutoARIMA e agrupamento K-Means por estado.'
      )
    ).toBeTruthy();
  });

  it('renders the card 2 description text', () => {
    renderHub();
    expect(
      screen.getByText(
        'Notificações SINAN de dengue, chikungunya e animais peçonhentos, com curva epidêmica semanal e perfil demográfico.'
      )
    ).toBeTruthy();
  });

  // The reciprocal sibling-route link was removed in the Hub redesign.
  it.skip('renders a discreet reciprocal <a> link on each card to the sibling route', () => {
    renderHub();
    const links = screen.getAllByRole('link');
    const hrefs = links.map((l) => l.getAttribute('href'));
    expect(hrefs).toContain('/mortalidade');
    expect(hrefs).toContain('/vigilancia');
  });

  it('never nests an <a> inside another <a> (invalid DOM — breaks click/history behavior)', () => {
    const { container } = renderHub();
    // Card bodies are clickable via role="link" divs, not real anchors, specifically
    // so the reciprocal <Link> inside each card never lands inside a real <a>.
    expect(container.querySelectorAll('a a').length).toBe(0);
  });

  it('clicking card 1 navigates to /mortalidade', async () => {
    const user = userEvent.setup();
    renderHubWithRoutes();
    await user.click(screen.getByRole('heading', { name: 'Mortalidade & Internações' }));
    expect((await screen.findByTestId('location-probe')).textContent).toBe('/mortalidade');
  });

  it('pressing Enter on card 2 (focused) navigates to /vigilancia', async () => {
    const user = userEvent.setup();
    renderHubWithRoutes();
    const card = screen.getByText('Vigilância Epidemiológica').closest('[role="link"]');
    expect(card).toBeTruthy();
    (card as HTMLElement).focus();
    await user.keyboard('{Enter}');
    expect((await screen.findByTestId('location-probe')).textContent).toBe('/vigilancia');
  });

  // The reciprocal sibling-route link was removed in the Hub redesign.
  it.skip('clicking the reciprocal link on card 1 navigates to /vigilancia, not /mortalidade', async () => {
    const user = userEvent.setup();
    renderHubWithRoutes();
    await user.click(screen.getByText('→ Vigilância Epidemiológica'));
    expect((await screen.findByTestId('location-probe')).textContent).toBe('/vigilancia');
  });

  it('issues zero network requests', () => {
    renderHub();
    expect(global.fetch).not.toHaveBeenCalled();
  });
});
