import React from 'react';
import {
  useFilterStore,
  DEFAULT_ANO_INICIO,
  DEFAULT_ANO_FIM,
} from '../store/filterStore';

interface ChipDef {
  field: string;
  label: string;
  value: string;
  clear: () => void;
}

export function ActiveFilterChips(): React.ReactElement | null {
  const store = useFilterStore();
  const {
    uf,
    municipio,
    cid_capitulo,
    cid_grupo,
    cid_codigo,
    faixa_etaria,
    sexo,
    ano_inicio,
    ano_fim,
  } = store;

  // Build chip list for every non-default active filter.
  // indicador is intentionally excluded — it always has a value (segmented control).
  const chips: ChipDef[] = [];

  if (uf !== '') {
    chips.push({ field: 'uf', label: 'UF', value: uf, clear: () => store.setUf('') });
  }
  if (municipio !== '') {
    chips.push({
      field: 'municipio',
      label: 'Município',
      value: municipio,
      clear: () => store.setMunicipio(''),
    });
  }
  if (cid_capitulo !== '') {
    chips.push({
      field: 'cid_capitulo',
      label: 'Capítulo',
      value: cid_capitulo,
      clear: () => store.setCidCapitulo(''),
    });
  }
  if (cid_grupo !== '') {
    chips.push({
      field: 'cid_grupo',
      label: 'Grupo',
      value: cid_grupo,
      clear: () => store.setCidGrupo(''),
    });
  }
  if (cid_codigo !== '') {
    chips.push({
      field: 'cid_codigo',
      label: 'CID',
      value: cid_codigo,
      clear: () => store.setCidCodigo(''),
    });
  }
  if (faixa_etaria !== '') {
    chips.push({
      field: 'faixa_etaria',
      label: 'Faixa',
      value: faixa_etaria,
      clear: () => store.setFaixaEtaria(''),
    });
  }
  if (sexo !== '') {
    chips.push({
      field: 'sexo',
      label: 'Sexo',
      value: sexo,
      clear: () => store.setSexo(''),
    });
  }
  // Period chip covers BOTH ano_inicio AND ano_fim as a single chip
  if (ano_inicio !== DEFAULT_ANO_INICIO || ano_fim !== DEFAULT_ANO_FIM) {
    chips.push({
      field: 'periodo',
      label: 'Período',
      value: `${ano_inicio}–${ano_fim}`,
      clear: () => {
        store.setAnoInicio(DEFAULT_ANO_INICIO);
        store.setAnoFim(DEFAULT_ANO_FIM);
      },
    });
  }

  // Zero active filters → render nothing (no DOM element at all)
  if (chips.length === 0) return null;

  const chipStyle: React.CSSProperties = {
    display: 'inline-flex',
    alignItems: 'center',
    gap: 5,
    background: 'var(--accent-soft)',
    border: '1px solid rgba(63,111,255,.25)',
    borderRadius: 'var(--radius-pill)',
    padding: '3px 6px 3px 10px',
    fontSize: 11.5,
    fontFamily: 'var(--font-ui)',
  };

  return (
    <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6 }}>
      {chips.map((chip) => (
        <span key={chip.field} style={chipStyle}>
          <span style={{ color: 'var(--text-muted)' }}>{chip.label} · </span>
          <span style={{ color: 'var(--text-secondary)', fontWeight: 500 }}>
            {chip.value}
          </span>
          <button
            type="button"
            onClick={chip.clear}
            aria-label={`Remover filtro ${chip.label}`}
            style={{
              background: 'none',
              border: 'none',
              color: 'var(--text-muted)',
              cursor: 'pointer',
              fontSize: 14,
              lineHeight: 1,
              padding: '0 2px 0 4px',
              display: 'flex',
              alignItems: 'center',
            }}
          >
            ×
          </button>
        </span>
      ))}
    </div>
  );
}
