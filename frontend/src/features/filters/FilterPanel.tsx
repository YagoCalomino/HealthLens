import React from 'react';
import { useQuery } from '@tanstack/react-query';
import { useFilterStore, syncToUrl } from '../../store/filterStore';
import { fetchUfs, fetchMunicipios } from '../../lib/api';
import { useCidHierarchy } from './useCidHierarchy';
import { PeriodSlider } from '../../components/PeriodSlider';
import { DEFAULT_ANO_INICIO, DEFAULT_ANO_FIM } from '../../store/filterStore';
import type { UFResponse, MunicipioResponse, CursorPage } from '../../types/api';

const FAIXA_ETARIA_OPTIONS = [
  { value: '', label: 'Todas as idades' },
  { value: '< 1 ano', label: '< 1 ano' },
  { value: '1-4 anos', label: '1–4 anos' },
  { value: '5-14 anos', label: '5–14 anos' },
  { value: '15-29 anos', label: '15–29 anos' },
  { value: '30-44 anos', label: '30–44 anos' },
  { value: '45-59 anos', label: '45–59 anos' },
  { value: '60-74 anos', label: '60–74 anos' },
  { value: '>= 75 anos', label: '≥ 75 anos' },
];

const SEXO_OPTIONS = [
  { value: '', label: 'Todos' },
  { value: 'M', label: 'Masculino' },
  { value: 'F', label: 'Feminino' },
  { value: 'I', label: 'Ignorado' },
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
  borderColor: 'rgba(91,141,239,.35)',
};

function selectStyle(active: boolean): React.CSSProperties {
  return active ? selectActive : selectBase;
}

// Section header: UPPERCASE label + horizontal rule + icon
function SectionHeader({
  icon,
  label,
}: {
  icon: React.ReactNode;
  label: string;
}): React.ReactElement {
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginBottom: 10 }}>
      {icon}
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
      <div
        style={{
          flex: 1,
          height: 1,
          background: 'var(--border-subtle)',
          marginLeft: 4,
        }}
      />
    </div>
  );
}

// SVG icon helpers — 14×14 viewport on 24×24 coordinate space
const PinIcon = (
  <svg width={14} height={14} viewBox="0 0 24 24" fill="var(--text-muted)">
    <path d="M12 2C8.13 2 5 5.13 5 9c0 5.25 7 13 7 13s7-7.75 7-13c0-3.87-3.13-7-7-7zm0 9.5c-1.38 0-2.5-1.12-2.5-2.5s1.12-2.5 2.5-2.5 2.5 1.12 2.5 2.5-1.12 2.5-2.5 2.5z" />
  </svg>
);

const CrossIcon = (
  <svg width={14} height={14} viewBox="0 0 24 24" fill="var(--text-muted)">
    <path d="M11 2v7H4v2h7v7h2v-7h7v-2h-7V2z" />
  </svg>
);

const UsersIcon = (
  <svg width={14} height={14} viewBox="0 0 24 24" fill="var(--text-muted)">
    <path d="M16 11c1.66 0 2.99-1.34 2.99-3S17.66 5 16 5c-1.66 0-3 1.34-3 3s1.34 3 3 3zm-8 0c1.66 0 2.99-1.34 2.99-3S9.66 5 8 5C6.34 5 5 6.34 5 8s1.34 3 3 3zm0 2c-2.33 0-7 1.17-7 3.5V19h14v-2.5c0-2.33-4.67-3.5-7-3.5zm8 0c-.29 0-.62.02-.97.05 1.16.84 1.97 1.97 1.97 3.45V19h6v-2.5c0-2.33-4.67-3.5-7-3.5z" />
  </svg>
);

const CalendarIcon = (
  <svg width={14} height={14} viewBox="0 0 24 24" fill="var(--text-muted)">
    <path d="M19 3h-1V1h-2v2H8V1H6v2H5c-1.11 0-1.99.9-1.99 2L3 19c0 1.1.89 2 2 2h14c1.1 0 2-.9 2-2V5c0-1.1-.9-2-2-2zm0 16H5V8h14v11zM7 10h5v5H7z" />
  </svg>
);

export function FilterPanel(): React.ReactElement {
  const store = useFilterStore();
  const { capitulos, isLoading: cidLoading, isError: cidError } = useCidHierarchy();

  // Fetch all UFs (non-paginated in practice — only 27 UFs)
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

  // CID cascade: find selected chapter and group
  const selectedCapitulo = capitulos.find((c) => c.id === store.cid_capitulo);
  const selectedGrupo = selectedCapitulo?.grupos.find((g) => g.id === store.cid_grupo);

  const handleReset = () => {
    store.reset();
    // Route-aware — never hardcodes '/', keeps the user on their current route
    // (see filterStore.syncToUrl for the same fix applied to the subscription path).
    syncToUrl(useFilterStore.getState());
  };

  const cidDisabled = cidLoading || cidError;
  const cidDisabledLabel = cidError ? 'Erro ao carregar CID-10' : 'Carregando...';

  // Active filter count — excludes indicador (always has a value)
  const activeCount = [
    store.uf !== '',
    store.municipio !== '',
    store.cid_capitulo !== '',
    store.cid_grupo !== '',
    store.cid_codigo !== '',
    store.faixa_etaria !== '',
    store.sexo !== '',
    store.ano_inicio !== DEFAULT_ANO_INICIO,
    store.ano_fim !== DEFAULT_ANO_FIM,
  ].filter(Boolean).length;

  return (
    <nav
      aria-label="Painel de filtros"
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
      {/* Panel header */}
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

      {/* Indicador segmented control — no section header, sits above the 4 sections */}
      <div
        style={{
          display: 'flex',
          gap: 4,
          padding: 4,
          background: 'var(--surface-control)',
          borderRadius: 10,
          marginBottom: 20,
        }}
      >
        {(['SIM', 'SIH'] as const).map((ind) => (
          <button
            key={ind}
            type="button"
            onClick={() => store.setIndicador(ind)}
            style={{
              flex: 1,
              border: 'none',
              borderRadius: 8,
              padding: '6px 4px',
              fontSize: 12,
              fontFamily: 'var(--font-ui)',
              cursor: 'pointer',
              background:
                store.indicador === ind
                  ? 'linear-gradient(180deg, #4673f0, #3f6fff)'
                  : 'transparent',
              color: store.indicador === ind ? '#fff' : 'var(--text-secondary)',
              fontWeight: store.indicador === ind ? 600 : 400,
            }}
          >
            {ind === 'SIM' ? 'Óbitos' : 'Internações'}
          </button>
        ))}
      </div>

      {/* Section: GEOGRAFIA */}
      <div style={{ marginBottom: 20 }}>
        <SectionHeader icon={PinIcon} label="GEOGRAFIA" />

        <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
          {/* UF */}
          <select
            id="filter-uf"
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

          {/* Município */}
          <select
            id="filter-municipio"
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
                  <option
                    key={m.codigo_ibge}
                    value={m.codigo_ibge}
                    style={{ color: m.tem_dados === false ? '#6B7689' : 'inherit' }}
                  >
                    {m.nome}{m.tem_dados === false ? ' (sem dados)' : ''}
                  </option>
                ))}
              </>
            ) : (
              <option value="">Selecione uma UF primeiro</option>
            )}
          </select>
        </div>
      </div>

      {/* Section: DOENÇA · CID-10 */}
      <div style={{ marginBottom: 20 }}>
        <SectionHeader icon={CrossIcon} label="DOENÇA · CID-10" />

        <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
          {/* Capítulo */}
          <select
            id="filter-cid-capitulo"
            style={selectStyle(store.cid_capitulo !== '')}
            value={store.cid_capitulo}
            onChange={(e) => store.setCidCapitulo(e.target.value)}
            disabled={cidDisabled}
            aria-label="Capítulo CID-10"
          >
            {cidDisabled ? (
              <option value="">{cidDisabledLabel}</option>
            ) : (
              <>
                <option value="">Todos os capítulos</option>
                {capitulos.map((c) => (
                  <option key={c.id} value={c.id}>
                    {c.id} — {c.descricao}
                  </option>
                ))}
              </>
            )}
          </select>

          {/* Grupo + Código side by side */}
          <div style={{ display: 'flex', gap: 8 }}>
            <select
              id="filter-cid-grupo"
              style={{ ...selectStyle(store.cid_grupo !== ''), flex: 1 }}
              value={store.cid_grupo}
              onChange={(e) => store.setCidGrupo(e.target.value)}
              disabled={cidDisabled || !store.cid_capitulo}
              aria-label="Grupo CID-10"
            >
              {!store.cid_capitulo || cidDisabled ? (
                <option value="">Todos os grupos</option>
              ) : selectedCapitulo && selectedCapitulo.grupos.length === 0 ? (
                <option value="" disabled>
                  — grupos não carregados —
                </option>
              ) : (
                <>
                  <option value="">Todos os grupos</option>
                  {(selectedCapitulo?.grupos ?? []).map((g) => (
                    <option key={g.id} value={g.id}>
                      {g.id} — {g.descricao}
                    </option>
                  ))}
                </>
              )}
            </select>

            <select
              id="filter-cid-codigo"
              style={{ ...selectStyle(store.cid_codigo !== ''), flex: 1 }}
              value={store.cid_codigo}
              onChange={(e) => store.setCidCodigo(e.target.value)}
              disabled={cidDisabled || !store.cid_grupo}
              aria-label="Código CID-10"
            >
              {!store.cid_grupo || cidDisabled ? (
                <option value="">Todos os códigos</option>
              ) : (
                <>
                  <option value="">Todos os códigos</option>
                  {(selectedGrupo?.codigos ?? []).map((c) => (
                    <option key={c.id} value={c.id}>
                      {c.id} — {c.descricao}
                    </option>
                  ))}
                </>
              )}
            </select>
          </div>
        </div>
      </div>

      {/* Section: DEMOGRAFIA */}
      <div style={{ marginBottom: 20 }}>
        <SectionHeader icon={UsersIcon} label="DEMOGRAFIA" />

        <div style={{ display: 'flex', gap: 8 }}>
          <select
            id="filter-faixa-etaria"
            style={{ ...selectStyle(store.faixa_etaria !== ''), flex: 1 }}
            value={store.faixa_etaria}
            onChange={(e) => store.setFaixaEtaria(e.target.value)}
            aria-label="Faixa Etária"
          >
            {FAIXA_ETARIA_OPTIONS.map((opt) => (
              <option key={opt.value} value={opt.value}>
                {opt.label}
              </option>
            ))}
          </select>

          <select
            id="filter-sexo"
            style={{ ...selectStyle(store.sexo !== ''), flex: 1 }}
            value={store.sexo}
            onChange={(e) => store.setSexo(e.target.value)}
            aria-label="Sexo"
          >
            {SEXO_OPTIONS.map((opt) => (
              <option key={opt.value} value={opt.value}>
                {opt.label}
              </option>
            ))}
          </select>
        </div>
      </div>

      {/* Section: PERÍODO */}
      <div style={{ marginBottom: 20 }}>
        <SectionHeader icon={CalendarIcon} label="PERÍODO" />
        <PeriodSlider
          anoInicio={store.ano_inicio}
          anoFim={store.ano_fim}
          onChange={(inicio, fim) => {
            store.setAnoInicio(inicio);
            store.setAnoFim(fim);
          }}
          min={2010}
          max={2025}
        />
      </div>
    </nav>
  );
}
