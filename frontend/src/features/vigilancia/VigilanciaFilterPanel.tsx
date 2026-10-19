import React from 'react';
import { useQuery } from '@tanstack/react-query';
import {
  useVigilanciaFilterStore,
  syncVigilanciaToUrl,
  VIGILANCIA_DEFAULT_ANO_INICIO,
  VIGILANCIA_DEFAULT_ANO_FIM,
} from '../../store/vigilanciaFilterStore';
import { fetchUfs, fetchMunicipios } from '../../lib/api';
import { PeriodSlider } from '../../components/PeriodSlider';
import type { UFResponse, MunicipioResponse, CursorPage } from '../../types/api';

// Portuguese labels transcribed from backend/app/constants/sinan.py::CLASSI_FIN_LABELS —
// duplicated here rather than fetched (no API endpoint surfaces this decode table yet).
// ANIM has no CLASSI_FIN column at all in the source data — no ANIM entry exists.
const CLASSI_FIN_OPTIONS: Record<'DENG' | 'CHIK', { value: string; label: string }[]> = {
  DENG: [
    { value: '0', label: 'Em investigação' },
    { value: '5', label: 'Descartado' },
    { value: '8', label: 'Inconclusivo' },
    { value: '10', label: 'Dengue' },
    { value: '11', label: 'Dengue com sinais de alarme' },
    { value: '12', label: 'Dengue grave' },
  ],
  CHIK: [
    { value: '0', label: 'Em investigação' },
    { value: '5', label: 'Descartado' },
    { value: '13', label: 'Chikungunya' },
  ],
};

const AGRAVO_OPTIONS: { value: 'DENG' | 'CHIK' | 'ANIM' | ''; label: string }[] = [
  { value: '', label: 'Todos os agravos' },
  { value: 'DENG', label: 'Dengue' },
  { value: 'CHIK', label: 'Chikungunya' },
  { value: 'ANIM', label: 'Animais peçonhentos' },
];

const selectBase: React.CSSProperties = {
  fontFamily: 'var(--font-ui)',
  fontSize: 12.5,
  background: 'var(--surface-control)',
  border: '1px solid var(--border-control)',
  borderRadius: 'var(--radius-md)',
  color: 'var(--text-primary)',
  width: '100%',
  padding: '9px 12px',
  outline: 'none',
};

const selectActive: React.CSSProperties = {
  ...selectBase,
  border: '1px solid rgba(91,141,239,.35)',
};

function selectStyle(active: boolean): React.CSSProperties {
  return active ? selectActive : selectBase;
}

function SectionHeader({ label }: { label: string }): React.ReactElement {
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginBottom: 10 }}>
      <span
        style={{
          fontFamily: 'var(--font-ui)',
          fontSize: 10,
          fontWeight: 600,
          color: 'var(--text-muted)',
          letterSpacing: '.7px',
          textTransform: 'uppercase',
        }}
      >
        {label}
      </span>
      <div style={{ flex: 1, height: 1, background: 'var(--border-subtle)', marginLeft: 4 }} />
    </div>
  );
}

export function VigilanciaFilterPanel(): React.ReactElement {
  const store = useVigilanciaFilterStore();

  const { data: ufsData } = useQuery<CursorPage<UFResponse>>({
    queryKey: ['ufs'],
    queryFn: () => fetchUfs(),
    staleTime: Infinity,
  });
  const ufs = ufsData?.items ?? [];

  const { data: municipios = [] } = useQuery<MunicipioResponse[]>({
    queryKey: ['municipios', store.uf],
    queryFn: () => fetchMunicipios(store.uf),
    enabled: !!store.uf,
    staleTime: 5 * 60 * 1000,
  });

  const handleReset = () => {
    store.reset();
    syncVigilanciaToUrl({
      agravo: '',
      uf: '',
      municipio: '',
      classi_fin: '',
      ano_inicio: VIGILANCIA_DEFAULT_ANO_INICIO,
      ano_fim: VIGILANCIA_DEFAULT_ANO_FIM,
    });
  };

  const classiFinOptions =
    store.agravo === 'DENG' || store.agravo === 'CHIK' ? CLASSI_FIN_OPTIONS[store.agravo] : null;
  const classiFinDisabled = classiFinOptions === null;

  const activeCount = [
    store.agravo !== '',
    store.uf !== '',
    store.municipio !== '',
    store.classi_fin !== '',
    store.ano_inicio !== VIGILANCIA_DEFAULT_ANO_INICIO,
    store.ano_fim !== VIGILANCIA_DEFAULT_ANO_FIM,
  ].filter(Boolean).length;

  return (
    <nav
      aria-label="Filtros de vigilância"
      style={{
        width: 296,
        height: '100%',
        background: 'var(--bg-panel)',
        padding: '16px 14px',
        overflowY: 'auto',
        display: 'flex',
        flexDirection: 'column',
        gap: 0,
      }}
    >
      <div style={{ display: 'flex', alignItems: 'center', marginBottom: 20 }}>
        <span
          style={{
            fontFamily: 'var(--font-ui)',
            fontSize: 13,
            fontWeight: 600,
            color: 'var(--text-primary)',
            flex: 1,
          }}
        >
          Filtros
        </span>
        {activeCount > 0 && (
          <span
            style={{
              background: 'var(--accent-soft)',
              color: '#9db4ff',
              borderRadius: 20,
              padding: '2px 8px',
              fontSize: 11,
              marginRight: 8,
            }}
          >
            {activeCount} ativos
          </span>
        )}
        <button
          type="button"
          onClick={handleReset}
          style={{
            background: 'none',
            border: 'none',
            fontFamily: 'var(--font-ui)',
            fontSize: 12,
            color: 'var(--text-secondary)',
            cursor: 'pointer',
            padding: 0,
          }}
        >
          Limpar
        </button>
      </div>

      <div style={{ marginBottom: 20 }}>
        <SectionHeader label="AGRAVO" />
        <select
          style={selectStyle(store.agravo !== '')}
          value={store.agravo}
          onChange={(e) => store.setAgravo(e.target.value as 'DENG' | 'CHIK' | 'ANIM' | '')}
          aria-label="Agravo"
        >
          {AGRAVO_OPTIONS.map((opt) => (
            <option key={opt.value} value={opt.value}>
              {opt.label}
            </option>
          ))}
        </select>
      </div>

      <div style={{ marginBottom: 20 }}>
        <SectionHeader label="GEOGRAFIA" />
        <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
          <select
            style={selectStyle(store.uf !== '')}
            value={store.uf}
            onChange={(e) => store.setUf(e.target.value)}
            aria-label="UF"
          >
            <option value="">Todas as UFs</option>
            {ufs.map((uf) => (
              <option key={uf.sigla} value={uf.sigla}>
                {uf.sigla} — {uf.nome}
              </option>
            ))}
          </select>

          <select
            style={selectStyle(store.municipio !== '')}
            value={store.municipio}
            onChange={(e) => store.setMunicipio(e.target.value)}
            disabled={!store.uf}
            aria-label="Município"
          >
            {store.uf ? (
              <>
                <option value="">Todos os municípios</option>
                {municipios.map((m) => (
                  <option key={m.codigo_ibge} value={m.codigo_ibge}>
                    {m.nome}
                  </option>
                ))}
              </>
            ) : (
              <option value="">Selecione uma UF primeiro</option>
            )}
          </select>
        </div>
      </div>

      <div style={{ marginBottom: 20 }}>
        <SectionHeader label="CLASSIFICAÇÃO" />
        <select
          style={selectStyle(store.classi_fin !== '')}
          value={store.classi_fin}
          onChange={(e) => store.setClassiFin(e.target.value)}
          disabled={classiFinDisabled}
          aria-label="Classificação final"
        >
          {classiFinDisabled ? (
            <option value="">Não se aplica</option>
          ) : (
            <>
              <option value="">Todas as classificações</option>
              {classiFinOptions.map((opt) => (
                <option key={opt.value} value={opt.value}>
                  {opt.label}
                </option>
              ))}
            </>
          )}
        </select>
      </div>

      <div style={{ marginBottom: 20 }}>
        <SectionHeader label="PERÍODO" />
        <PeriodSlider
          anoInicio={store.ano_inicio}
          anoFim={store.ano_fim}
          onChange={(inicio, fim) => {
            store.setAnoInicio(inicio);
            store.setAnoFim(fim);
          }}
          min={2015}
          max={2025}
        />
      </div>
    </nav>
  );
}
