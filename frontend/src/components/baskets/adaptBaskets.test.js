import { describe, expect, it } from 'vitest';

import fixture from './baskets.fixture.json';
import {
  BASKET_FIELDS,
  adaptBaskets,
  adaptField,
  cacheNote,
  dominantBinShare,
  edgeText,
  histogramBins,
  histogramCoverage,
  interiorGaps,
  percentileRows,
} from './adaptBaskets.js';

/** The fixture is the unmodified response from GET /analytics/baskets. */

describe('adaptBaskets', () => {
  it('reads the invoice count and the endpoint’s interpretation', () => {
    const o = adaptBaskets(fixture);
    expect(o.invoices).toBe(39529);
    expect(o.interpretation).toContain('Chen, Sain and Guo (2012)');
  });

  it('survives an empty payload', () => {
    expect(adaptBaskets(undefined).invoices).toBeNull();
  });
});

describe('edgeText', () => {
  it('drops precision as magnitude rises', () => {
    // An axis tick reading 1,107.00 is two characters of noise; one reading
    // "0" where the value is 0.19 is wrong.
    expect(edgeText(0.19, '£')).toBe('£0.19');
    expect(edgeText(22.933607807263343)).toBe('22.9');
    expect(edgeText(1107)).toBe('1,107');
  });

  it('renders an absent edge as a dash, not as NaN', () => {
    expect(edgeText(null)).toBe('—');
    expect(edgeText(undefined)).toBe('—');
  });
});

describe('histogramBins', () => {
  it('pairs each count with its interval', () => {
    const { bins } = histogramBins(fixture.order_value.histogram_log, { currency: '£' });
    expect(bins).toHaveLength(40);
    expect(bins[0].axis).toBe('£0.19');
    expect(bins[0].label).toBe('£0.19 to £0.27');
  });

  it('returns nothing rather than throwing on a missing histogram', () => {
    expect(histogramBins(undefined).bins).toEqual([]);
  });
});

describe('interiorGaps', () => {
  it('counts empty bins between populated ones and ignores an empty tail', () => {
    const bins = [1, 0, 2, 0, 0].map((value, i) => ({ key: i, value }));
    expect(interiorGaps(bins)).toBe(1);
  });

  it('finds the whole-number artefact in the distinct-items log histogram', () => {
    // Six bins narrower than one item, which cannot contain an observation.
    const field = adaptField(fixture, 'distinct_items_per_invoice');
    expect(field.histograms.log.gaps).toBe(6);
    expect(field.integer).toBe(true);
  });

  it('is zero when every bin up to the last is populated', () => {
    expect(interiorGaps([{ value: 3 }, { value: 1 }])).toBe(0);
    expect(interiorGaps([])).toBe(0);
  });
});

describe('histogramCoverage', () => {
  it('notices the invoice the log histogram loses on its top edge', () => {
    // The largest order sits exactly on the final edge and lands a hair
    // outside it in floating point. One invoice changes nothing; a histogram
    // that silently drops observations should still say so.
    const field = adaptField(fixture, 'order_value');
    expect(field.histograms.log.coverage.plotted).toBe(39528);
    expect(field.histograms.log.coverage.missing).toBe(1);
  });

  it('reports full coverage where there is nothing missing', () => {
    const field = adaptField(fixture, 'distinct_items_per_invoice');
    expect(field.histograms.linear.coverage.missing).toBe(0);
    expect(field.histograms.log.coverage.missing).toBe(0);
  });
});

describe('percentileRows', () => {
  it('orders string-keyed percentiles numerically', () => {
    const rows = percentileRows(fixture.order_value.percentiles);
    expect(rows.map((r) => r.p)).toEqual([1, 5, 10, 25, 50, 75, 90, 95, 99]);
    expect(rows.find((r) => r.p === 50).value).toBeCloseTo(301.2, 2);
  });

  it('returns an empty list for a missing block', () => {
    expect(percentileRows(null)).toEqual([]);
  });
});

describe('adaptField', () => {
  it('takes the default scale from the endpoint, not from preference', () => {
    // Hard-coding "always log" would be the same mistake in the opposite
    // direction on a dataset that is not skewed.
    for (const meta of BASKET_FIELDS) {
      const field = adaptField(fixture, meta.key);
      expect(field.stronglySkewed).toBe(true);
      expect(field.defaultScale).toBe('log');
    }
  });

  it('prepares both histograms so the toggle has nothing to compute', () => {
    const field = adaptField(fixture, 'order_value');
    expect(field.histograms.linear.bins).toHaveLength(40);
    expect(field.histograms.log.bins).toHaveLength(40);
    expect(field.histograms.log.logScale).toBe(true);
    expect(field.histograms.linear.logScale).toBe(false);
  });

  it('is null for a field the response does not carry', () => {
    expect(adaptField(fixture, 'not_a_field')).toBeNull();
  });
});

describe('dominantBinShare', () => {
  it('quantifies why the linear view of order value is unreadable', () => {
    // 99% of invoices in the first of forty bars. Quoting the figure lets a
    // reader check the claim rather than take it on trust.
    const field = adaptField(fixture, 'order_value');
    expect(dominantBinShare(field.histograms.linear.bins)).toBeCloseTo(0.9905, 4);
    expect(dominantBinShare(field.histograms.log.bins)).toBeCloseTo(0.1903, 4);
  });

  it('is null when there is nothing to divide by', () => {
    expect(dominantBinShare([])).toBeNull();
  });
});

describe('cacheNote', () => {
  it('reports a cold computation as a duration', () => {
    expect(cacheNote(fixture)).toBe('Computed for this request in 10.8s.');
  });

  it('distinguishes a cache hit', () => {
    expect(cacheNote({ _cache: { hit: true, computed_ms: 10762 } })).toBe(
      'Served from cache, originally computed in 10.8s.',
    );
  });

  it('is null when no cache block is reported', () => {
    expect(cacheNote({})).toBeNull();
  });
});
