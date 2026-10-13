// A row's total_eventos is "reliable" when it's not far below what that same
// location normally reports — SIM (óbitos) and SIH (internações) have wildly
// different absolute scales, and so does every UF/município relative to every
// other, so no single fixed count works as a floor. Instead each location's
// own median total_eventos across its years is the baseline, and a year below
// RELIABILITY_RATIO of that median is treated as partial coverage / a sample
// artifact and excluded from trend and display calculations.
export const RELIABILITY_RATIO = 0.1;

export function median(values: number[]): number {
  if (values.length === 0) return 0;
  const sorted = values.slice().sort((a, b) => a - b);
  const mid = Math.floor(sorted.length / 2);
  return sorted.length % 2 !== 0 ? sorted[mid] : (sorted[mid - 1] + sorted[mid]) / 2;
}

export function computeMedianByKey<T extends { total_eventos: number | null }>(
  rows: T[],
  keyFn: (row: T) => string
): Map<string, number> {
  const groups = new Map<string, number[]>();
  for (const r of rows) {
    const key = keyFn(r);
    const g = groups.get(key);
    if (g) g.push(r.total_eventos ?? 0);
    else groups.set(key, [r.total_eventos ?? 0]);
  }
  const result = new Map<string, number>();
  for (const [key, eventos] of groups) {
    result.set(key, median(eventos));
  }
  return result;
}

export function isReliableRow<T extends { total_eventos: number | null }>(
  row: T,
  key: string,
  medianByKey: Map<string, number>
): boolean {
  const locationMedian = medianByKey.get(key) ?? 0;
  return (row.total_eventos ?? 0) >= locationMedian * RELIABILITY_RATIO;
}

export function filterReliableRows<T extends { total_eventos: number | null }>(
  rows: T[],
  keyFn: (row: T) => string
): T[] {
  const medianByKey = computeMedianByKey(rows, keyFn);
  return rows.filter((r) => isReliableRow(r, keyFn(r), medianByKey));
}
