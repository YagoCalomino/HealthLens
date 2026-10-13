// Mirrors backend/app/schemas/*.py exactly — field names and nullability must stay in sync.

// backend/app/schemas/geo.py
export interface UFResponse {
  sigla: string;
  nome: string;
  codigo_ibge: string;
  codigo_topojson: string;
}

export interface MunicipioResponse {
  codigo_ibge: string;
  nome: string;
  sigla_uf: string;
  codigo_topojson: string;
  tem_dados?: boolean;
}

// backend/app/schemas/indicadores.py
export interface IndicadorResponse {
  sigla_uf: string;
  codigo_ibge: string | null;
  nome_municipio: string | null;
  ano: number;
  total_eventos: number;
  populacao: number | null;
  taxa_por_100k: number | null;
  fonte: 'SIM' | 'SIH';
}

// backend/app/schemas/forecasts.py
export interface HistoricoItem {
  ano: number;
  valor: number | null;
}

export interface PrevisaoItem {
  ano: number;
  valor_previsto: number;
  ci80_inf: number | null;
  ci80_sup: number | null;
  ci95_inf: number | null;
  ci95_sup: number | null;
}

export interface ModeloDetalhe {
  mase: number | null;
  smape: number | null;
  previsoes: PrevisaoItem[];
}

export interface MunicipioInfo {
  codigo_ibge_6: string;
  nome_municipio: string;
  sigla_uf: string;
}

export interface ForecastResponse {
  municipio: MunicipioInfo;
  metrica: string;
  ano_referencia: number;
  historico: HistoricoItem[];
  modelos: Record<string, ModeloDetalhe>;
}

// backend/app/schemas/clusters.py
export interface ClusterItemResponse {
  codigo_ibge_6: string;
  codigo_ibge_7: string;
  nome_municipio: string;
  sigla_uf: string;
  cluster_id: number;
  cluster_nome: string | null;
  pca_x: number | null;
  pca_y: number | null;
  centroid_pca_x: number | null;
  centroid_pca_y: number | null;
  features_norm: Record<string, number> | null;
  silhouette_score: number | null;
  ano_referencia: number;
}

// backend/app/schemas/clusters.py — national-view UF aggregate
export interface ClusterUfSummaryResponse {
  sigla_uf: string;
  cluster_id: number;
  cluster_nome: string | null;
  pca_x: number | null;
  pca_y: number | null;
  n_municipios: number;
  ano_referencia: number;
}

// backend/app/schemas/notificacoes.py
export type AgravoCodigo = 'DENG' | 'CHIK' | 'ANIM';

export interface NotificacaoResponse {
  id: number;
  agravo: AgravoCodigo;
  sigla_uf: string;
  codigo_ibge: string | null;
  nome_municipio: string | null;
  ano: number;
  mes: number | null;
  dt_notific: string | null;
  semana_epidemiologica: number | null;
  ano_epidemiologico: number | null;
  sexo: string | null;
  idade_anos: number | null;
  faixa_etaria: string | null;
  classi_fin: number | null;
  classi_fin_label: string | null;
  gravidade_grave: boolean | null;
  tra_classi: number | null;
  tra_classi_label: string | null;
  tp_acidente: number | null;
  tp_acidente_label: string | null;
  taxa_por_100k: number | null;
}

export interface NotificacaoSummaryResponse {
  sigla_uf: string;
  codigo_ibge: string | null;
  nome_municipio: string | null;
  ano: number;
  agravo: AgravoCodigo;
  total_notificacoes: number;
  taxa_por_100k: number | null;
}

export interface CurvaEpidemicaResponse {
  ano_epidemiologico: number;
  semana_epidemiologica: number;
  total_notificacoes: number;
  taxa_por_100k: number | null;
}

export interface BreakdownResponse {
  campo: string;
  categoria: string | null;
  codigo: number | string | null;
  total_notificacoes: number;
}

// fastapi-pagination cursor envelope — all list endpoints
export interface CursorPage<T> {
  items: T[];
  total: number | null;
  current_page: string | null;
  current_page_backwards: string | null;
  previous_page: string | null;
  next_page: string | null;
}
