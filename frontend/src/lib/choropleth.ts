// Choropleth 5-class warm scale — taxa_por_100k visualization
export const CHORO_5 = ['#F4D99A', '#E8A85C', '#D97A4E', '#B8473B', '#7F2723'] as const;

// K-Means cluster palette — 6 distinct hues for epidemiological profiles
export const CLUSTER_6 = ['#6F9BFF', '#4FD1B0', '#F0B35B', '#C77DFF', '#F0846B', '#B8473B'] as const;

// PT-BR labels for each cluster level — rendered in ClusterView legend
export const CLUSTER_LABELS = ['Baixa', 'Baixa-Moderada', 'Moderada', 'Moderada-Alta', 'Alta', 'Crítica'] as const;

// Neutral fill for municipalities/UFs with no data for the current filter — never a CHORO_5 class.
export const NO_DATA_COLOR = '#222A37';

export interface QuantileScale {
  color: (v: number | null | undefined) => string;
  thresholds: number[];
}

/**
 * Builds a 5-class quantile color scale over `data` (typically taxa_por_100k values).
 * Thresholds are recomputed per call so the legend always reflects the current filtered dataset
 * (quantile classification recalculated on every filter change, never a fixed domain).
 */
export function getQuantileScale(
  data: (number | null | undefined)[],
  colors: readonly string[] = CHORO_5
): QuantileScale {
  // Exclude zero and negative values — they are treated as "sem dado" identical to null.
  // Including zeros in the quantile would collapse all breakpoints to 0 when only a few
  // features have non-zero data (e.g. sparse sample), producing degenerate labels like
  // "< 0" / "0–0". The color() function below maps v ≤ 0 to NO_DATA_COLOR.
  const values = data
    .filter((v): v is number => typeof v === 'number' && !Number.isNaN(v) && v > 0)
    .slice()
    .sort((a, b) => a - b);

  if (values.length === 0) {
    return {
      color: () => NO_DATA_COLOR,
      thresholds: [],
    };
  }

  // Quantile breaks computed from actual data — adapts to any value range
  // (sample data 0.09–0.46 or production data 10–80 per 100k).
  const q = (p: number): number => values[Math.floor(p * values.length)] ?? values[values.length - 1] ?? 0;
  const thresholds = [q(0.2), q(0.4), q(0.6), q(0.8)];

  const color = (v: number | null | undefined): string => {
    if (v == null || Number.isNaN(v) || v <= 0) {
      return NO_DATA_COLOR;
    }
    let bucket = 0;
    for (let i = 0; i < thresholds.length; i++) {
      if (v > thresholds[i]) {
        bucket = i + 1;
      }
    }
    return colors[bucket];
  };

  return { color, thresholds };
}
