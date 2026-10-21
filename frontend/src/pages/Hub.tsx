import React from 'react';
import { useNavigate } from 'react-router-dom';

const CARDS = [
  {
    to: '/mortalidade',
    accentVar: 'var(--accent)',
    label: 'Mortalidade & Internações',
    title: 'Mortalidade & Internações',
    description: 'Óbitos e internações do SUS por local, tempo e causa, com série temporal, previsão AutoARIMA e agrupamento K-Means por estado.',
    stats: [
      { value: '576.921', label: 'Óbitos registrados' },
      { value: '904.303', label: 'Internações' },
    ],
    tags: ['SIM · DataSUS', 'SIH · DataSUS', 'CID-10', '2014–2023'],
    footer: '27 estados · 5.570 municípios',
    sparkline: '0,52 16,48 32,50 48,40 64,42 80,28 96,32 112,18 128,22 144,10 160,14',
  },
  {
    to: '/vigilancia',
    accentVar: 'var(--neg)',
    label: 'Vigilância',
    title: 'Vigilância Epidemiológica',
    description: 'Notificações SINAN de dengue, chikungunya e animais peçonhentos, com curva epidêmica semanal e perfil demográfico.',
    stats: [
      { value: '13M', label: 'Notificações SINAN' },
      { value: '3', label: 'Agravos monitorados' },
    ],
    tags: ['SINAN', 'Dengue · Chik · Anim', '2015–2025'],
    footer: '3 agravos · 27 UFs',
    sparkline: '0,48 12,36 24,44 36,16 48,30 60,6 72,26 84,40 96,26 108,44 120,34 132,50 144,40 160,44',
  },
] as const;

function HubCard({ card }: { card: typeof CARDS[number] }): React.ReactElement {
  const navigate = useNavigate();
  const [hovered, setHovered] = React.useState(false);

  return (
    <div
      role="link"
      tabIndex={0}
      onClick={() => navigate(card.to)}
      onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); navigate(card.to); } }}
      onMouseEnter={() => setHovered(true)}
      onMouseLeave={() => setHovered(false)}
      style={{
        display: 'flex',
        flexDirection: 'column',
        background: 'var(--surface-card)',
        border: `1px solid ${hovered ? card.accentVar : 'color-mix(in oklab, ' + card.accentVar + ' 22%, transparent)'}`,
        borderRadius: 'var(--radius-lg)',
        padding: '32px',
        position: 'relative',
        overflow: 'hidden',
        cursor: 'pointer',
        transition: 'border-color var(--transition-base), transform var(--transition-base)',
        transform: hovered ? 'translateY(-2px)' : 'translateY(0)',
        fontFamily: "'Times New Roman', Times, serif",
      }}
    >
      {/* Sparkline */}
      <div style={{ position: 'absolute', top: 24, right: 24, width: 160, height: 64, opacity: 0.5, pointerEvents: 'none' }}>
        <svg viewBox="0 0 160 64" style={{ width: '100%', height: '100%' }}>
          <polyline points={card.sparkline} fill="none" stroke={card.accentVar} strokeWidth="1.5" opacity="0.55" />
        </svg>
      </div>

      {/* Label */}
      <div style={{ fontSize: 13, letterSpacing: '0.06em', color: card.accentVar, textTransform: 'uppercase', marginBottom: 18 }}>
        {card.label}
      </div>

      {/* Title */}
      <h2 style={{ fontSize: 26, fontWeight: 600, margin: '0 0 12px 0', color: card.accentVar, fontFamily: "'Times New Roman', Times, serif" }}>
        {card.title}
      </h2>

      {/* Description */}
      <p style={{ fontSize: 15, lineHeight: 1.6, color: 'var(--text-secondary)', maxWidth: 440, margin: '0 0 28px 0' }}>
        {card.description}
      </p>

      {/* Stats */}
      <div style={{ display: 'flex', gap: 36, marginBottom: 24, flexWrap: 'wrap' }}>
        {card.stats.map((s) => (
          <div key={s.label}>
            <div style={{ fontFamily: "'Times New Roman', Times, serif", fontSize: 30, fontWeight: 500, color: 'var(--text-primary)', lineHeight: 1 }}>{s.value}</div>
            <div style={{ fontSize: 11, letterSpacing: '0.06em', color: 'var(--text-muted)', textTransform: 'uppercase', marginTop: 6 }}>{s.label}</div>
          </div>
        ))}
      </div>

      {/* Tags */}
      <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', marginBottom: 20 }}>
        {card.tags.map((tag) => (
          <span key={tag} style={{ fontSize: 11, letterSpacing: '0.04em', color: card.accentVar, border: `1px solid color-mix(in oklab, ${card.accentVar} 40%, transparent)`, borderRadius: 'var(--radius-sm)', padding: '4px 8px' }}>
            {tag}
          </span>
        ))}
      </div>

      {/* Footer */}
      <div style={{ marginTop: 'auto', paddingTop: 18, borderTop: '1px solid color-mix(in oklab, var(--text-primary) 8%, transparent)' }}>
        <span style={{ fontSize: 12, color: 'var(--text-muted)' }}>{card.footer}</span>
      </div>
    </div>
  );
}

export default function Hub(): React.ReactElement {
  return (
    <div style={{ background: 'var(--bg-base)', minHeight: '100vh', fontFamily: "'Times New Roman', Times, serif", color: 'var(--text-primary)', position: 'relative' }}>
      <div style={{ maxWidth: 960, margin: '0 auto', padding: '72px 40px 96px' }}>

        {/* Hero */}
        <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', textAlign: 'center', gap: 6, marginBottom: 56 }}>
          <div style={{ fontSize: 14, letterSpacing: '0.08em', color: 'var(--text-muted)', textTransform: 'uppercase' }}>HealthLens</div>
          <div style={{ fontSize: 13, letterSpacing: '0.06em', color: 'var(--text-muted)' }}>DataSUS · SIM · SIH · SINAN</div>
          <h1 style={{ fontSize: 'clamp(2rem, 4vw, 2.75rem)', fontWeight: 600, lineHeight: 1.15, margin: '16px 0 12px 0', maxWidth: 640, letterSpacing: 0, whiteSpace: 'nowrap', fontFamily: "'Times New Roman', Times, serif" }}>
            Análise de saúde pública brasileira
          </h1>
          <p style={{ fontSize: 17, lineHeight: 1.6, color: 'var(--text-secondary)', maxWidth: 560, margin: 0 }}>
            Mortalidade, internações e vigilância epidemiológica a partir de dados oficiais do DataSUS, de 2015 a 2023.
          </p>
        </div>

        {/* Cards */}
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 24, alignItems: 'stretch' }}>
          {CARDS.map((card) => <HubCard key={card.to} card={card} />)}
        </div>

        {/* Footer */}
        <div style={{ marginTop: 64, fontSize: 12, letterSpacing: '0.05em', color: 'var(--text-muted)', textAlign: 'center' }}>
          Fonte oficial: DataSUS / Ministério da Saúde
        </div>

      </div>
    </div>
  );
}
