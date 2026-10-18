import { describe, it, expect } from 'vitest';
import { getQuantileScale, CHORO_5, NO_DATA_COLOR } from './choropleth';

describe('getQuantileScale', () => {
  it('returns NO_DATA_COLOR for any input and empty thresholds when data is empty', () => {
    const { color, thresholds } = getQuantileScale([], CHORO_5);
    // Empty / all-zero data → no quantile classes; every value maps to no-data sentinel.
    expect(color(0)).toBe(NO_DATA_COLOR);
    expect(color(1000)).toBe(NO_DATA_COLOR);
    expect(color(null)).toBe(NO_DATA_COLOR);
    expect(thresholds).toEqual([]);
  });

  it('returns NO_DATA_COLOR for zero and negative values even with valid data present', () => {
    const data = [1, 5, 10, 50, 100];
    const { color } = getQuantileScale(data, CHORO_5);
    expect(color(0)).toBe(NO_DATA_COLOR);
    expect(color(-1)).toBe(NO_DATA_COLOR);
  });

  it('returns CHORO_5[0] for the lowest 20% and CHORO_5[4] for the highest 20% of a known dataset', () => {
    // 100 evenly spaced values, 1..100 — clean 20% buckets.
    const data = Array.from({ length: 100 }, (_, i) => i + 1);
    const { color } = getQuantileScale(data, CHORO_5);

    expect(color(1)).toBe(CHORO_5[0]);
    expect(color(10)).toBe(CHORO_5[0]);
    expect(color(100)).toBe(CHORO_5[4]);
    expect(color(95)).toBe(CHORO_5[4]);
  });

  it('returns a stable color for a value exactly on a quantile boundary (no off-by-one)', () => {
    const data = Array.from({ length: 100 }, (_, i) => i + 1);
    const { thresholds, color } = getQuantileScale(data, CHORO_5);

    expect(thresholds).toHaveLength(4);

    // A value exactly equal to a boundary belongs to the lower bucket (bucket changes only when v > threshold).
    for (let i = 0; i < thresholds.length; i++) {
      const boundary = thresholds[i];
      const c1 = color(boundary);
      const c2 = color(boundary);
      expect(c1).toBe(c2); // stable / deterministic
      expect(c1).toBe(CHORO_5[i]);
    }
  });

  it('returns exactly 4 boundary thresholds for 5 classes', () => {
    const data = Array.from({ length: 37 }, (_, i) => i * 3.7);
    const { thresholds } = getQuantileScale(data, CHORO_5);
    expect(thresholds).toHaveLength(4);
  });

  it('maps null/NaN taxa values to NO_DATA_COLOR, never a CHORO_5 class', () => {
    const data = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10];
    const { color } = getQuantileScale(data, CHORO_5);

    expect(color(null)).toBe(NO_DATA_COLOR);
    expect(color(undefined)).toBe(NO_DATA_COLOR);
    expect(color(NaN)).toBe(NO_DATA_COLOR);
    expect(CHORO_5).not.toContain(NO_DATA_COLOR);
  });
});
