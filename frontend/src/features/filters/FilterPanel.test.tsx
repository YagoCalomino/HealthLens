/**
 * FilterPanel.test.tsx
 *
 * Tests the CID-10 cascade logic:
 * 1. Selecting a chapter with groups enables Grupo select with those groups.
 * 2. Selecting a chapter with empty grupos shows disabled "— grupos não carregados —".
 * 3. After selecting a grupo then changing the capítulo, cid_grupo/cid_codigo are reset.
 */
import React from 'react';
import { describe, it, expect, beforeEach, vi } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';

// Must mock before importing FilterPanel so the module resolution picks up the mock
vi.mock('./useCidHierarchy', () => ({
  useCidHierarchy: () => ({
    isLoading: false,
    isError: false,
    capitulos: [
      {
        id: 'IX',
        descricao: 'Doenças do aparelho circulatório',
        grupos: [
          {
            id: 'I20-I25',
            descricao: 'Doenças isquêmicas do coração',
            codigos: [{ id: 'I21', descricao: 'Infarto agudo do miocárdio' }],
          },
          {
            id: 'I60-I69',
            descricao: 'Doenças cerebrovasculares',
            codigos: [],
          },
        ],
      },
      {
        id: 'II',
        descricao: 'Neoplasias (tumores)',
        grupos: [], // empty — should trigger "— grupos não carregados —"
      },
    ],
  }),
}));

// Mock the api module to prevent real fetch calls from UF/municipio queries
vi.mock('../../lib/api', () => ({
  fetchUfs: () => Promise.resolve({ items: [], total: null, current_page: null, current_page_backwards: null, previous_page: null, next_page: null }),
  fetchMunicipios: () => Promise.resolve([]),
  fetchClustersPage: () => Promise.resolve({ items: [], total: null, current_page: null, current_page_backwards: null, previous_page: null, next_page: null }),
}));

import { FilterPanel } from './FilterPanel';
import { useFilterStore } from '../../store/filterStore';

function makeQueryClient() {
  return new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
}

function Wrapper({ children }: { children: React.ReactNode }) {
  return (
    <QueryClientProvider client={makeQueryClient()}>
      {children}
    </QueryClientProvider>
  );
}

describe('FilterPanel CID-10 cascade', () => {
  beforeEach(() => {
    // Reset Zustand store to defaults before each test
    useFilterStore.getState().reset();
  });

  it('selecting chapter IX enables Grupo select with that chapters groups', () => {
    render(<FilterPanel />, { wrapper: Wrapper });

    const capitulo = screen.getByLabelText('Capítulo CID-10');
    fireEvent.change(capitulo, { target: { value: 'IX' } });

    // Store should now have cid_capitulo = 'IX'
    expect(useFilterStore.getState().cid_capitulo).toBe('IX');

    const grupo = screen.getByLabelText('Grupo CID-10') as HTMLSelectElement;
    expect(grupo.disabled).toBe(false);

    // Group options should include the chapter IX groups
    expect(screen.getByText('I20-I25 — Doenças isquêmicas do coração')).toBeTruthy();
    expect(screen.getByText('I60-I69 — Doenças cerebrovasculares')).toBeTruthy();
  });

  it('selecting chapter II shows the disabled "— grupos não carregados —" option', () => {
    render(<FilterPanel />, { wrapper: Wrapper });

    const capitulo = screen.getByLabelText('Capítulo CID-10');
    fireEvent.change(capitulo, { target: { value: 'II' } });

    expect(useFilterStore.getState().cid_capitulo).toBe('II');

    // The disabled option must be present in the DOM
    const disabledOption = screen.getByText('— grupos não carregados —');
    expect(disabledOption).toBeTruthy();
    // The option itself should be disabled
    expect((disabledOption as HTMLOptionElement).disabled).toBe(true);
  });

  it('after selecting a grupo then changing capitulo, cid_grupo and cid_codigo are reset', () => {
    render(<FilterPanel />, { wrapper: Wrapper });

    // Step 1: select chapter IX
    const capitulo = screen.getByLabelText('Capítulo CID-10');
    fireEvent.change(capitulo, { target: { value: 'IX' } });
    expect(useFilterStore.getState().cid_capitulo).toBe('IX');

    // Step 2: select grupo I20-I25 — setCidCapitulo already reset it, now set grupo
    const grupo = screen.getByLabelText('Grupo CID-10');
    fireEvent.change(grupo, { target: { value: 'I20-I25' } });
    expect(useFilterStore.getState().cid_grupo).toBe('I20-I25');

    // Step 3: change capitulo to II — store.setCidCapitulo resets cid_grupo + cid_codigo
    fireEvent.change(capitulo, { target: { value: 'II' } });

    const state = useFilterStore.getState();
    expect(state.cid_capitulo).toBe('II');
    expect(state.cid_grupo).toBe('');
    expect(state.cid_codigo).toBe('');
  });
});
