/**
 * useNotificacoes.test.ts — mocks global.fetch and asserts request URLs and the
 * three-parallel-request shape of useMultiAgravoComparison.
 */
import React from 'react';
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { renderHook, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';

import {
  useMultiAgravoComparison,
  useNotificacoesUfSummary,
} from './useNotificacoes';
import { useVigilanciaFilterStore, VIGILANCIA_DEFAULT_STATE } from '../../store/vigilanciaFilterStore';

const EMPTY_LIST: unknown[] = [];

function makeQueryClient() {
  return new QueryClient({ defaultOptions: { queries: { retry: false } } });
}

function Wrapper({ children }: { children: React.ReactNode }) {
  return React.createElement(QueryClientProvider, { client: makeQueryClient() }, children);
}

describe('useNotificacoes', () => {
  beforeEach(() => {
    useVigilanciaFilterStore.setState({ ...VIGILANCIA_DEFAULT_STATE });
    global.fetch = vi.fn(() =>
      Promise.resolve(new Response(JSON.stringify(EMPTY_LIST), { status: 200 }))
    ) as typeof global.fetch;
  });

  afterEach(() => {
    vi.clearAllMocks();
  });

  it('fetchNotificacoesUfSummary requests the exact expected URL', async () => {
    useVigilanciaFilterStore.setState({
      agravo: 'DENG',
      uf: 'SP',
      ano_inicio: 2023,
      ano_fim: 2024,
    });

    const { result } = renderHook(() => useNotificacoesUfSummary(), { wrapper: Wrapper });

    await waitFor(() => expect(result.current.isLoading).toBe(false));

    const fetchMock = global.fetch as unknown as ReturnType<typeof vi.fn>;
    const calledUrl = String(fetchMock.mock.calls[0]?.[0]);
    expect(calledUrl).toContain('/notificacoes/uf-summary?agravo=DENG&uf=SP&ano_inicio=2023&ano_fim=2024');
  });

  it('useMultiAgravoComparison triggers exactly 3 fetch calls with agravo=DENG, CHIK, ANIM', async () => {
    useVigilanciaFilterStore.setState({ uf: 'SP' });

    const { result } = renderHook(() => useMultiAgravoComparison(), { wrapper: Wrapper });

    await waitFor(() => expect(result.current.every((slot) => !slot.isLoading)).toBe(true));

    const fetchMock = global.fetch as unknown as ReturnType<typeof vi.fn>;
    expect(fetchMock.mock.calls.length).toBe(3);

    const calledUrls = fetchMock.mock.calls.map((call) => String(call[0]));
    expect(calledUrls.some((u) => u.includes('agravo=DENG'))).toBe(true);
    expect(calledUrls.some((u) => u.includes('agravo=CHIK'))).toBe(true);
    expect(calledUrls.some((u) => u.includes('agravo=ANIM'))).toBe(true);

    // Never a comma-joined agravo param.
    expect(calledUrls.some((u) => u.includes('DENG,CHIK') || u.includes('DENG%2CCHIK'))).toBe(false);

    expect(result.current.map((slot) => slot.agravo)).toEqual(['DENG', 'CHIK', 'ANIM']);
  });

  it('useMultiAgravoComparison uses municipio-summary when a município is selected', async () => {
    useVigilanciaFilterStore.setState({ uf: 'SP', municipio: '355030' });

    const { result } = renderHook(() => useMultiAgravoComparison(), { wrapper: Wrapper });

    await waitFor(() => expect(result.current.every((slot) => !slot.isLoading)).toBe(true));

    const fetchMock = global.fetch as unknown as ReturnType<typeof vi.fn>;
    const calledUrls = fetchMock.mock.calls.map((call) => String(call[0]));
    expect(calledUrls.every((u) => u.includes('/notificacoes/municipio-summary'))).toBe(true);
  });

  it('surfaces a non-2xx response as isError, not a thrown render error', async () => {
    global.fetch = vi.fn(() =>
      Promise.resolve(new Response('Internal Server Error', { status: 500 }))
    ) as typeof global.fetch;

    const { result } = renderHook(() => useNotificacoesUfSummary(), { wrapper: Wrapper });

    await waitFor(() => expect(result.current.isError).toBe(true));
    expect(result.current.rows).toEqual([]);
  });
});
