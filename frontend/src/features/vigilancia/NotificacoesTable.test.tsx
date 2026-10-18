/**
 * NotificacoesTable.test.tsx — raw-record drill-down + CSV export tests.
 *
 * Mocks fetchNotificacoesPage directly (avoids real network calls); uses a
 * real QueryClientProvider since the component calls useQuery itself.
 */
import React from 'react';
import { describe, it, expect, beforeEach, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';

vi.mock('../../lib/api', () => ({
  fetchNotificacoesPage: vi.fn(),
}));

import { NotificacoesTable, buildNotificacoesCsv } from './NotificacoesTable';
import { fetchNotificacoesPage } from '../../lib/api';
import { useVigilanciaFilterStore, VIGILANCIA_DEFAULT_STATE } from '../../store/vigilanciaFilterStore';
import type { NotificacaoResponse } from '../../types/api';

const mockFetchNotificacoesPage = vi.mocked(fetchNotificacoesPage);

function makeQueryClient() {
  return new QueryClient({ defaultOptions: { queries: { retry: false } } });
}

function Wrapper({ children }: { children: React.ReactNode }) {
  return <QueryClientProvider client={makeQueryClient()}>{children}</QueryClientProvider>;
}

function notificacaoRow(overrides: Partial<NotificacaoResponse>): NotificacaoResponse {
  return {
    id: 1,
    agravo: 'ANIM',
    sigla_uf: 'SP',
    codigo_ibge: '3550308',
    nome_municipio: 'São Paulo',
    ano: 2023,
    mes: 5,
    dt_notific: '2023-05-10',
    semana_epidemiologica: 19,
    ano_epidemiologico: 2023,
    sexo: 'M',
    idade_anos: 34,
    faixa_etaria: '30-39',
    classi_fin: null,
    classi_fin_label: null,
    gravidade_grave: null,
    tra_classi: 1,
    tra_classi_label: 'Leve',
    tp_acidente: 1,
    tp_acidente_label: 'Serpente',
    taxa_por_100k: 0.5,
    ...overrides,
  };
}

describe('buildNotificacoesCsv', () => {
  it('quotes a field containing a comma', () => {
    const rows = [notificacaoRow({ nome_municipio: 'Santo André, SP' })];
    const csv = buildNotificacoesCsv(rows);
    expect(csv).toContain('"Santo André, SP"');
  });

  it('the first line is the header row and the line count equals rows.length + 1', () => {
    const rows = [notificacaoRow({}), notificacaoRow({ id: 2 })];
    const csv = buildNotificacoesCsv(rows);
    const lines = csv.split('\n');
    expect(lines[0]).toContain('Município');
    expect(lines).toHaveLength(rows.length + 1);
  });

  it('never includes numero_notificacao', () => {
    const rows = [notificacaoRow({})];
    const csv = buildNotificacoesCsv(rows);
    expect(csv).not.toContain('numero_notificacao');
  });
});

describe('NotificacoesTable', () => {
  beforeEach(() => {
    useVigilanciaFilterStore.setState({ ...VIGILANCIA_DEFAULT_STATE });
    vi.clearAllMocks();
  });

  it('issues no fetch when both uf and municipio are empty', () => {
    useVigilanciaFilterStore.setState({ uf: '', municipio: '' });

    render(<NotificacoesTable />, { wrapper: Wrapper });

    expect(mockFetchNotificacoesPage).not.toHaveBeenCalled();
  });

  it('disables the export button for an empty result set', async () => {
    useVigilanciaFilterStore.setState({ uf: 'SP' });
    mockFetchNotificacoesPage.mockResolvedValue([]);

    render(<NotificacoesTable />, { wrapper: Wrapper });

    const button = await screen.findByRole('button', { name: 'Exportar CSV' });
    expect(button.hasAttribute('disabled')).toBe(true);
  });

  it('enables the export button and lists rows when a UF filter is active', async () => {
    useVigilanciaFilterStore.setState({ uf: 'SP' });
    mockFetchNotificacoesPage.mockResolvedValue([notificacaoRow({})]);

    render(<NotificacoesTable />, { wrapper: Wrapper });

    const button = await screen.findByRole('button', { name: 'Exportar CSV' });
    expect(button.hasAttribute('disabled')).toBe(false);
    expect(await screen.findByText('São Paulo')).toBeTruthy();
  });
});
