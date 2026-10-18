import React, { useEffect } from 'react';
import { Link } from 'react-router-dom';
import '../App.css';

import {
  hydrateVigilanciaFromUrl,
  subscribeVigilanciaUrlSync,
  useVigilanciaFilterStore,
} from '../store/vigilanciaFilterStore';
import { ErrorBoundary } from '../components/ErrorBoundary';
import { Card } from '../components/Card';
import { VigilanciaFilterPanel } from '../features/vigilancia/VigilanciaFilterPanel';
import { MultiAgravoCard } from '../features/vigilancia/MultiAgravoCard';
import { EpidemicCurve } from '../features/vigilancia/EpidemicCurve';
import { NotificationChoropleth } from '../features/vigilancia/NotificationChoropleth';
import { SeverityBreakdown } from '../features/vigilancia/SeverityBreakdown';
import { AgeSexBreakdown } from '../features/vigilancia/AgeSexBreakdown';
import { NotificacoesTable } from '../features/vigilancia/NotificacoesTable';

// Hydrate store from URL before first render — module-level guard, mirrors App.tsx.
// hydrateVigilanciaFromUrl validates every param: agravo against the literal
// union, classi_fin/ano_* through Number()/isNaN guards, unknown params ignored.
hydrateVigilanciaFromUrl();

const regionGridStyle: React.CSSProperties = {
  flex: 1,
  minHeight: 0,
  display: 'flex',
  flexDirection: 'column',
  gap: 'var(--space-8)',
  overflowY: 'auto',
  padding: 'var(--space-6)',
};

export default function VigilanciaPanel(): React.ReactElement {
  const { agravo } = useVigilanciaFilterStore();

  // Subscribe URL sync after mount — fires on every filter change (mirrors App.tsx).
  useEffect(() => {
    const unsub = subscribeVigilanciaUrlSync();
    return unsub;
  }, []);

  return (
    <div className="app-root">
      <header className="dashboard-topbar">
        <div className="topbar-left">
          <Link to="/" className="topbar-brand" style={{ textDecoration: 'none', color: 'inherit' }}>
            HealthLens
          </Link>
          <span className="topbar-brand"> · Vigilância Epidemiológica</span>
        </div>
        <div className="topbar-right">
          <Link
            to="/mortalidade"
            style={{
              fontFamily: 'var(--font-ui)',
              fontSize: 'var(--text-xs)',
              fontWeight: 600,
              textTransform: 'uppercase',
              color: 'var(--text-muted)',
              textDecoration: 'none',
            }}
          >
            · Mortalidade & Internações
          </Link>
        </div>
      </header>

      <div className="dashboard-body">
        <aside className="dashboard-sidebar">
          <VigilanciaFilterPanel />
        </aside>

        <main style={regionGridStyle}>
          <div data-testid="vigilancia-comparacao">
            <ErrorBoundary context="comparação por agravo" fallbackTitle="Erro ao carregar comparação">
              <Card title="Comparação por agravo">
                <MultiAgravoCard />
              </Card>
            </ErrorBoundary>
          </div>

          <div data-testid="vigilancia-curva">
            <ErrorBoundary context="curva epidêmica" fallbackTitle="Erro ao carregar curva epidêmica">
              <Card title="Curva epidêmica por semana epidemiológica">
                <EpidemicCurve />
              </Card>
            </ErrorBoundary>
          </div>

          <div data-testid="vigilancia-mapa">
            <ErrorBoundary context="mapa de notificações" fallbackTitle="Erro ao carregar mapa">
              <Card title="Taxa de notificação por 100 mil">
                <NotificationChoropleth />
              </Card>
            </ErrorBoundary>
          </div>

          <div data-testid="vigilancia-breakdowns" style={{ display: 'flex', flexDirection: 'column', gap: 'var(--space-8)' }}>
            {agravo !== '' && (
              <ErrorBoundary context="notificações por classificação e gravidade" fallbackTitle="Erro ao carregar detalhamento">
                <Card title="Notificações por classificação e gravidade">
                  <SeverityBreakdown />
                </Card>
              </ErrorBoundary>
            )}
            <ErrorBoundary context="notificações por faixa etária e sexo" fallbackTitle="Erro ao carregar detalhamento">
              <Card title="Notificações por faixa etária e sexo">
                <AgeSexBreakdown />
              </Card>
            </ErrorBoundary>
          </div>

          <div data-testid="vigilancia-tabela">
            <ErrorBoundary context="tabela de notificações" fallbackTitle="Erro ao carregar tabela">
              <Card title="Notificações — registros">
                <NotificacoesTable />
              </Card>
            </ErrorBoundary>
          </div>
        </main>
      </div>
    </div>
  );
}
