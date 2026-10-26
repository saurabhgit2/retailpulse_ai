import { describe, expect, it } from 'vitest';

import { axisFormatter, axisUnit, compact, dateTick, pickDateTicks } from './axisFormat.js';

describe('axisUnit', () => {
  it('chooses one unit for the whole axis from its largest tick', () => {
    // The point of this function: 800 / 900 / 1K / 1.1K makes the reader
    // change scale halfway up the column.
    expect(axisUnit([0, 400, 800, 1200]).suffix).toBe('K');
  });
});

describe('axisFormatter', () => {
  it('applies that one unit to every tick', () => {
    const f = axisFormatter([0, 400, 800, 1200]);
    expect([0, 400, 800, 1200].map(f)).toEqual(['0.0K', '0.4K', '0.8K', '1.2K']);
  });

  it('uses whole numbers when the ticks are whole', () => {
    const f = axisFormatter([0, 1000, 2000, 3000]);
    expect(f(2000)).toBe('2K');
  });

  it('carries a currency prefix inside the sign', () => {
    const f = axisFormatter([-2000, 0, 2000], { currency: '£' });
    expect(f(-2000)).toBe('-£2K');
  });

  it('renders an unplottable tick as nothing, not as NaN', () => {
    expect(axisFormatter([0, 10])(null)).toBe('');
  });
});

describe('compact', () => {
  it('shortens large numbers and keeps small ones intact', () => {
    expect(compact(1_250_000, { currency: '£' })).toBe('£1.3M');
    expect(compact(842)).toBe('842');
  });

  it('keeps a significant digit on a headline figure', () => {
    // £17,743,000 must not read "£18M": rounding away 0.7 of a million on
    // the number a dashboard leads with is a three-quarter-million error.
    expect(compact(17_743_000, { currency: '£' })).toBe('£17.7M');
    expect(compact(99_668, { currency: '£' })).toBe('£99.7K');
    expect(compact(164_459, { currency: '£' })).toBe('£164K');
  });

  it('shows an em dash for a value that is genuinely absent', () => {
    // Not "0": a KPI with no source column is unknown, not zero.
    expect(compact(null)).toBe('—');
  });
});

describe('dateTick', () => {
  it('reads a timestamp in UTC', () => {
    // 23:30 UTC on the 5th is the 6th in New Zealand. Formatting in the
    // viewer's zone would move every weekly bucket by one day.
    expect(dateTick('2011-12-05T23:30:00Z')).toBe('5 Dec');
  });

  it('returns an empty string for an unparseable value', () => {
    expect(dateTick('not a date')).toBe('');
  });
});

describe('pickDateTicks', () => {
  it('thins the labels to what fits', () => {
    const indices = pickDateTicks(Array.from({ length: 104 }, (_, i) => i), 600);
    expect(indices.length).toBeLessThanOrEqual(10);
  });

  it('always labels the last point', () => {
    const values = Array.from({ length: 53 }, (_, i) => i);
    const indices = pickDateTicks(values, 400);
    expect(indices[indices.length - 1]).toBe(52);
  });

  it('drops the tick the forced last label would overlap', () => {
    // 107 weekly points in 560px: the old rule compared the remainder
    // against the stride, kept both, and the final two labels collided on
    // screen. The gap has to be measured where it is seen, in pixels.
    const weeks = Array.from({ length: 107 }, (_, i) => i);
    const indices = pickDateTicks(weeks, 560);
    const perPoint = 560 / 106;
    const gap = (indices[indices.length - 1] - indices[indices.length - 2]) * perPoint;
    expect(gap).toBeGreaterThanOrEqual(64);
  });

  it('keeps every label when they all fit', () => {
    expect(pickDateTicks([1, 2, 3], 600)).toEqual([0, 1, 2]);
  });
});
