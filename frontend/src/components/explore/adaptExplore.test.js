import { describe, expect, it } from 'vitest';

import distributionsFixture from './distributions.fixture.json';
import seasonalityFixture from './seasonality.fixture.json';
import {
  CALENDAR_DIMENSIONS,
  adaptCalendar,
  adaptRevenueDistribution,
  bucketLabel,
  cacheNote,
  decompositionDiagnostics,
  decompositionSeries,
} from './adaptExplore.js';
import { shareText } from '../shared/histogramShape.js';

/**
 * Both fixtures are unmodified responses: GET /analytics/seasonality and
 * GET /analytics/distributions.
 */

describe('bucketLabel', () => {
  it('turns an hour bucket into a clock time', () => {
    // The endpoint labels them "6.0", which is the float that came out of the
    // grouping rather than a time anyone reads.
    expect(bucketLabel('hour', 6, '6.0')).toBe('06:00');
    expect(bucketLabel('hour', 21, '21.0')).toBe('21:00');
  });

  it('leaves days and months as the endpoint named them', () => {
    expect(bucketLabel('month', 0, 'January')).toBe('January');
    expect(bucketLabel('day_of_week', 5, 'Saturday')).toBe('Saturday');
  });
});

describe('adaptCalendar', () => {
  it('reads all three profiles', () => {
    const counts = CALENDAR_DIMENSIONS.map((d) => adaptCalendar(seasonalityFixture, d.key).bins.length);
    expect(counts).toEqual([7, 12, 16]);
  });

  it('keeps unreliable buckets and marks them', () => {
    // Seven Saturdays in two years. Dropping it would hide that this
    // retailer barely trades on Saturdays, which is the finding.
    const days = adaptCalendar(seasonalityFixture, 'day_of_week');
    const saturday = days.bins.find((b) => b.label === 'Saturday');
    expect(saturday.reliable).toBe(false);
    expect(saturday.observations).toBe(7);
    expect(days.unreliable.map((b) => b.label)).toEqual(['Saturday']);
  });

  it('flags the two one-observation hours', () => {
    const hours = adaptCalendar(seasonalityFixture, 'hour');
    expect(hours.unreliable.map((b) => b.label)).toEqual(['06:00', '21:00']);
  });

  it('carries the index as the plotted value', () => {
    const months = adaptCalendar(seasonalityFixture, 'month');
    const peak = months.bins.reduce((a, b) => (b.value > a.value ? b : a));
    expect(peak.label).toBe('November');
    expect(peak.value).toBeCloseTo(1.603, 3);
  });

  it('is null for a dimension the response does not carry', () => {
    expect(adaptCalendar(seasonalityFixture, 'quarter')).toBeNull();
    expect(adaptCalendar(undefined, 'month')).toBeNull();
  });
});

describe('decompositionDiagnostics', () => {
  it('works out that each seasonal phase rests on one observation', () => {
    // The endpoint's own note says "about 2 observations". The centred
    // 52-week average consumes 26 points at each end of 104, leaving 52
    // trend points for 52 phases, so the real figure is one.
    const d = decompositionDiagnostics(seasonalityFixture);
    expect(d.points).toBe(104);
    expect(d.trendPoints).toBe(52);
    expect(d.observationsPerPhase).toBe(1);
  });

  it('detects a degenerate remainder', () => {
    // Every residual is the same number to twelve decimal places, so the
    // seasonal component absorbed the whole detrended series.
    const d = decompositionDiagnostics(seasonalityFixture);
    expect(d.remainderDegenerate).toBe(true);
    expect(d.remainderSpread).toBeLessThan(1e-6);
  });

  it('does not call a varying remainder degenerate', () => {
    const payload = {
      decomposition: {
        available: true,
        period: 2,
        index: ['a', 'b', 'c', 'd'],
        observed: [10, 20, 30, 40],
        trend: [null, 20, 30, null],
        remainder: [null, 1, 5, null],
      },
    };
    expect(decompositionDiagnostics(payload).remainderDegenerate).toBe(false);
  });

  it('scales its tolerance to the data rather than using a fixed epsilon', () => {
    // A spread of 0.5 is nothing beside values near a million and everything
    // beside values near one.
    const big = {
      decomposition: {
        available: true,
        period: 2,
        index: ['a', 'b', 'c', 'd'],
        observed: [1, 1_000_000, 1, 1_000_000],
        trend: [null, 1, 1, null],
        remainder: [null, 0.0001, 0.0002, null],
      },
    };
    expect(decompositionDiagnostics(big).remainderDegenerate).toBe(true);
  });

  it('reports unavailability rather than throwing', () => {
    expect(decompositionDiagnostics({}).available).toBe(false);
    expect(decompositionDiagnostics({ decomposition: { available: false } }).available).toBe(false);
  });
});

describe('decompositionSeries', () => {
  it('returns parallel arrays with gaps preserved as null', () => {
    // The trend is undefined for the first and last 26 weeks, and those have
    // to stay null so the line is drawn with gaps rather than through them.
    const s = decompositionSeries(seasonalityFixture);
    expect(s.x).toHaveLength(104);
    expect(s.trend[0]).toBeNull();
    expect(s.trend[103]).toBeNull();
    expect(s.trend.filter((v) => v !== null)).toHaveLength(52);
    expect(s.observed.filter((v) => v !== null)).toHaveLength(104);
  });

  it('returns empty arrays for a missing decomposition', () => {
    expect(decompositionSeries({}).x).toEqual([]);
  });
});

describe('adaptRevenueDistribution', () => {
  it('opens on the log scale, because the endpoint says the field is skewed', () => {
    const r = adaptRevenueDistribution(distributionsFixture);
    expect(r.defaultScale).toBe('log');
    expect(r.count).toBe(1003430);
  });

  it('loses one line to the top edge, and says so', () => {
    const r = adaptRevenueDistribution(distributionsFixture);
    expect(r.histograms.log.coverage.missing).toBe(1);
  });

  it('is null for a missing payload', () => {
    expect(adaptRevenueDistribution(undefined)).toBeNull();
  });
});

describe('shareText', () => {
  it('does not round a share short of the whole up to 100%', () => {
    // 1,003,412 of 1,003,430 is not every line, and "100.0%" says it is.
    const share = 1003412 / 1003430;
    expect(shareText(share)).not.toBe('100.0%');
    expect(shareText(share)).toBe('99.998%');
  });

  it('leaves an ordinary share at the requested precision', () => {
    expect(shareText(0.9905)).toBe('99.1%');
    expect(shareText(0.5)).toBe('50.0%');
  });

  it('prints a genuine whole as 100%', () => {
    expect(shareText(1)).toBe('100.0%');
  });

  it('renders an absent share as a dash', () => {
    expect(shareText(null)).toBe('—');
  });
});

describe('cacheNote', () => {
  it('reports the cold computation of each endpoint', () => {
    expect(cacheNote(seasonalityFixture)).toBe('Computed for this request in 3.6s.');
    expect(cacheNote(distributionsFixture)).toBe('Computed for this request in 10.5s.');
  });
});
