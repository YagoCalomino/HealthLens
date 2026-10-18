import React from 'react';

export interface BreadcrumbProps {
  /** UF sigla (e.g. "SP") — undefined means national view (breadcrumb hidden). */
  sigla_uf?: string;
  /** Nome of the currently selected municipality — shown when present. */
  nome_municipio?: string;
  /** Callback to clear uf + municipio and return to the national view. */
  onHome: () => void;
}

/**
 * Breadcrumb navigation for the choropleth map.
 *
 * National view: renders nothing.
 * Municipal view: "Brasil ›‹sigla_uf›" — and "› {nome_municipio}" when a
 * municipality is selected.
 *
 * "›" separator is U+203A (SINGLE RIGHT-POINTING ANGLE QUOTATION MARK).
 * "Brasil" is a native <button> (not <a>) so it is keyboard-focusable and
 * triggers onHome without a page navigation.
 */
export function Breadcrumb({
  sigla_uf,
  nome_municipio,
  onHome,
}: BreadcrumbProps): React.ReactElement | null {
  // Hidden in national view
  if (!sigla_uf) return null;

  return (
    <nav
      aria-label="Localização atual no mapa"
      style={{
        fontFamily: 'var(--font-ui)',
        fontSize: 'var(--text-base)',
        color: 'var(--text-secondary)',
        display: 'flex',
        alignItems: 'center',
        gap: '0.25rem',
        flexWrap: 'wrap',
      }}
    >
      {/* "Brasil" — native button, keyboard-focusable, calls onHome */}
      <button
        type="button"
        aria-label="Voltar para visão nacional"
        onClick={onHome}
        style={{
          fontFamily: 'var(--font-ui)',
          fontSize: 'var(--text-base)',
          fontWeight: 'var(--weight-regular)',
          color: 'var(--accent)',
          background: 'none',
          border: 'none',
          padding: 0,
          cursor: 'pointer',
          textDecoration: 'none',
        }}
        onMouseEnter={(e) => {
          (e.currentTarget as HTMLButtonElement).style.textDecoration = 'underline';
        }}
        onMouseLeave={(e) => {
          (e.currentTarget as HTMLButtonElement).style.textDecoration = 'none';
        }}
      >
        Brasil
      </button>

      {/* Single right-pointing angle quotation mark (U+203A) */}
      <span aria-hidden="true">›</span>

      <span>{sigla_uf}</span>

      {nome_municipio && (
        <>
          <span aria-hidden="true">›</span>
          <span>{nome_municipio}</span>
        </>
      )}
    </nav>
  );
}
