import { describe, expect, it } from 'vitest';

import fixture from './rfm.fixture.json';
import {
  MONETARY_BANDS,
  RECENCY_BANDS,
  adaptOverview,
  adaptSegments,
  bandCounts,
  cacheNote,
  methodNotes,
  monetaryBands,
  recencyBands,
  recencySplit,
  segmentLabel,
  segmentSlope,
  topCustomers,
} from './adaptRfm.js';

/**
 * The fixture is the real response from `GET /analytics/rfm`, with the
 * 5,875-row table replaced by twelve real rows chosen to land in several
 * bands at once. Everything else is untouched, so a change to the endpoint's
 * shape fails here rather than in the browser.
 */

describe('adaptOverview', () => {
  it('reads coverage, concentration and the medians', () => {
    const o = adaptOverview(fixture);
    expect(o.guestShare).toBeCloseTo(0.136, 3);
    expect(o.concentration.gini).toBeCloseTo(0.7359, 4);
    expect(o.concentration.topShare).toBeCloseTo(0.7671, 4);
    expect(o.negativeCustomers).toBe(27);
    expect(o.asOf).toBe('2011-12-09');
  });

  it('keeps the concentration headcount separate from the customer count', () => {
    // 5,875 customers but concentration over 5,831 entities. The page has to
    // be able to say so; collapsing them into one number is how a dashboard
    // ends up contradicting itself on the next page.
    const o = adaptOverview(fixture);
    expect(o.concentration.entities).toBe(5831);
    expect(o.concentration.entities).not.toBe(o.customers);
  });

  it('reports a missing figure as null, never as zero', () => {
    const o = adaptOverview({});
    expect(o.customers).toBeNull();
    expect(o.guestShare).toBeNull();
    expect(o.concentration.gini).toBeNull();
  });
});

describe('adaptSegments', () => {
  it('orders the segments by revenue, not by headcount', () => {
    const rows = adaptSegments(fixture);
    expect(rows[0].key).toBe('champions');
    expect(rows[rows.length - 1].key).toBe('new');
  });

  it('carries the median profile of each segment', () => {
    const hibernating = adaptSegments(fixture).find((s) => s.key === 'hibernating');
    expect(hibernating.medianFrequency).toBe(1);
    expect(hibernating.medianRecency).toBe(384);
    expect(hibernating.label).toBe('Hibernating');
  });
});

describe('segmentLabel', () => {
  it('turns a snake_case key into a sentence-case label', () => {
    expect(segmentLabel('potential_loyalist')).toBe('Potential loyalist');
    expect(segmentLabel('at_risk')).toBe('At risk');
  });
});

describe('segmentSlope', () => {
  it('puts the headcount ranking against the revenue ranking', () => {
    const rows = segmentSlope(adaptSegments(fixture));
    const hibernating = rows.find((r) => r.key === 'hibernating');
    const champions = rows.find((r) => r.key === 'champions');

    // The finding the chart exists to show: the biggest group of customers
    // is the smallest slice of the money, and the orderings cross.
    expect(hibernating.leftRank).toBe(1);
    expect(hibernating.rightRank).toBe(3);
    expect(champions.leftRank).toBe(2);
    expect(champions.rightRank).toBe(1);
  });

  it('ranks every segment exactly once on each side', () => {
    const rows = segmentSlope(adaptSegments(fixture));
    const left = rows.map((r) => r.leftRank).sort((a, b) => a - b);
    const right = rows.map((r) => r.rightRank).sort((a, b) => a - b);
    const expected = rows.map((_, i) => i + 1);
    expect(left).toEqual(expected);
    expect(right).toEqual(expected);
  });
});

describe('bandCounts', () => {
  it('treats the upper bound as inclusive, so a boundary value is counted once', () => {
    const { bins } = bandCounts([100, 100.01], MONETARY_BANDS);
    expect(bins.find((b) => b.key === 'lt100').value).toBe(1);
    expect(bins.find((b) => b.key === 'lt250').value).toBe(1);
  });

  it('counts a non-finite value as skipped rather than as zero', () => {
    // Binning a null as 0 would move a customer whose value is unknown into
    // the "£0 or less" bar, which is a claim about them that is not true.
    const { bins, skipped } = bandCounts([null, Number.NaN, 50], MONETARY_BANDS);
    expect(skipped).toBe(2);
    expect(bins.reduce((sum, b) => sum + b.value, 0)).toBe(1);
  });
});

describe('monetaryBands', () => {
  it('gives negative customers a bucket of their own', () => {
    const { bins } = monetaryBands(fixture);
    expect(bins[0].label).toBe('£0 or less');
    expect(bins[0].value).toBe(2);
  });

  it('bins every row in the table and loses none', () => {
    const { bins, skipped } = monetaryBands(fixture);
    expect(bins.reduce((sum, b) => sum + b.value, 0) + skipped).toBe(fixture.table.length);
    expect(bins.find((b) => b.key === 'ge25k').value).toBe(4);
    expect(bins.find((b) => b.key === 'lt100').value).toBe(3);
  });
});

describe('recencyBands', () => {
  it('bins recency into the periods a retailer already thinks in', () => {
    const { bins } = recencyBands(fixture);
    expect(bins.find((b) => b.key === 'd30').value).toBe(5);
    expect(bins.find((b) => b.key === 'y15').value).toBe(3);
    expect(bins.reduce((sum, b) => sum + b.value, 0)).toBe(fixture.table.length);
  });

  it('covers every day with exactly one band', () => {
    for (let day = 0; day <= 900; day += 1) {
      const matches = RECENCY_BANDS.filter((b, i) => {
        const lower = i === 0 ? -Infinity : RECENCY_BANDS[i - 1].upper;
        return day > lower && day <= b.upper;
      });
      expect(matches).toHaveLength(1);
    }
  });
});

describe('recencySplit', () => {
  it('reads the two ends of the distribution off the bars', () => {
    const { bins } = recencyBands(fixture);
    const split = recencySplit(bins);
    expect(split.recent).toBe(5);
    expect(split.dormant).toBe(4);
    expect(split.recentShare).toBeCloseTo(5 / 12, 6);
  });

  it('counts each band into at most one end', () => {
    const { bins } = recencyBands(fixture);
    const split = recencySplit(bins);
    expect(split.recent + split.dormant).toBeLessThanOrEqual(split.total);
  });

  it('returns nulls rather than dividing by zero', () => {
    expect(recencySplit([]).recentShare).toBeNull();
  });
});

describe('topCustomers', () => {
  it('ranks by net value and shares against identified revenue', () => {
    const rows = topCustomers(fixture, 3);
    expect(rows.map((r) => r.key)).toEqual(['18102', '14646', '14156']);
    // Guest revenue has no customer to attribute it to, so it is not in the
    // denominator; including it would understate every share shown.
    expect(rows[0].share).toBeCloseTo(578408.64 / fixture.coverage.identified_revenue, 6);
    expect(rows[0].segment).toBe('Champions');
  });

  it('returns an empty list rather than throwing when there is no table', () => {
    expect(topCustomers({})).toEqual([]);
  });
});

describe('methodNotes', () => {
  it('carries the endpoint’s own caveats through unchanged', () => {
    const notes = methodNotes(fixture);
    expect(notes.caveats).toHaveLength(3);
    expect(notes.clustering).toHaveLength(2);
    expect(notes.caveats.join(' ')).toContain('Recency is measured from the end of the data');
  });
});

describe('cacheNote', () => {
  it('says when a cached result was computed', () => {
    expect(cacheNote(fixture)).toMatch(/^Served from cache, computed 28 Oct/);
  });

  it('reports a fresh computation as a duration', () => {
    expect(cacheNote({ _cache: { hit: false, computed_ms: 5855 } })).toBe(
      'Computed for this request in 5.9s.',
    );
  });

  it('is null when the endpoint does not report a cache', () => {
    expect(cacheNote({})).toBeNull();
  });
});
