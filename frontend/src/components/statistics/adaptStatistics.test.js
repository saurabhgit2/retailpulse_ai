import { describe, expect, it } from 'vitest';

import featuresFixture from './features.fixture.json';
import statisticsFixture from './statistics.fixture.json';
import {
  adaptComparison,
  adaptDescriptive,
  adaptFeatures,
  adaptNormality,
  adaptStationarity,
  adaptTest,
  binRange,
  fieldLabel,
  rankDisagreements,
} from './adaptStatistics.js';

/**
 * Both fixtures are unmodified responses: GET /analytics/statistics and
 * GET /analytics/features.
 */

describe('fieldLabel', () => {
  it('turns a snake_case field into a readable label', () => {
    expect(fieldLabel('avg_unit_price')).toBe('Avg unit price');
    expect(fieldLabel('')).toBe('—');
  });
});

describe('adaptDescriptive', () => {
  it('reads the headline block with the variable it describes', () => {
    const d = adaptDescriptive(statisticsFixture);
    expect(d.value).toBe('order_value');
    expect(d.group).toBe('quarter');
    expect(d.n).toBe(39529);
    expect(d.median).toBeCloseTo(301.2, 2);
    expect(d.skewness).toBeCloseTo(50.55, 2);
  });

  it('returns nulls rather than zeros for an empty payload', () => {
    const d = adaptDescriptive({});
    expect(d.n).toBeNull();
    expect(d.median).toBeNull();
  });
});

describe('adaptNormality', () => {
  it('carries the verdict and the reason no test was run', () => {
    // The refusal to run a normality test is a methodological position, not a
    // missing feature, so the reason has to survive to the page.
    const n = adaptNormality(statisticsFixture);
    expect(n.available).toBe(true);
    expect(n.verdict).toBe('strongly right-skewed');
    expect(n.note).toContain('deliberately not reported');
  });

  it('reports unavailability rather than throwing', () => {
    expect(adaptNormality({}).available).toBe(false);
  });
});

describe('adaptComparison', () => {
  it('plots the median of each group', () => {
    const c = adaptComparison(statisticsFixture);
    expect(c.groups.map((g) => g.label)).toEqual(['Q1', 'Q2', 'Q3', 'Q4']);
    expect(c.groups[0].value).toBe(c.groups[0].median);
  });

  it('measures how far apart the group medians actually are', () => {
    // 304.98 - 297.94. This is the quantity the p-value should be weighed
    // against, and it is seven pounds on a median of three hundred.
    const c = adaptComparison(statisticsFixture);
    expect(c.medianSpread).toBeCloseTo(7.04, 2);
  });

  it('is null when the response carries no comparison', () => {
    expect(adaptComparison({})).toBeNull();
  });
});

describe('adaptTest', () => {
  it('leads with the effect size when a significant result is negligible', () => {
    // p = 0.00046 with epsilon squared = 0.0004. Leading with the p-value
    // would invert the finding: this is a statement about having 39,529
    // observations, not about the quarters.
    const t = adaptComparison(statisticsFixture).test;
    expect(t.significant).toBe(true);
    expect(t.effect.magnitude).toBe('negligible');
    expect(t.headline).toBe('effect');
    expect(t.interpretationNote).toContain('Read the effect size, not the p-value');
  });

  it('leads with significance when the effect is not negligible', () => {
    const t = adaptTest({
      name: 'Kruskal-Wallis H',
      significant: true,
      effect_size: { name: 'epsilon squared', value: 0.21, magnitude: 'moderate' },
    });
    expect(t.headline).toBe('significance');
  });

  it('leads with significance when the result is not significant', () => {
    const t = adaptTest({
      significant: false,
      effect_size: { magnitude: 'negligible' },
    });
    expect(t.headline).toBe('significance');
  });

  it('is null when no test was run', () => {
    expect(adaptTest(null)).toBeNull();
  });
});

describe('adaptStationarity', () => {
  it('reports why it is absent rather than showing an empty slot', () => {
    const s = adaptStationarity(statisticsFixture);
    expect(s.available).toBe(false);
    expect(s.reason).toContain('forecasting engine');
  });
});

describe('adaptFeatures', () => {
  it('reads every feature with both estimates', () => {
    const f = adaptFeatures(featuresFixture);
    expect(f.features).toHaveLength(17);
    expect(f.features[0].key).toBe('gross_revenue');
    expect(f.features[0].miKnn).toBeCloseTo(1.059, 3);
    expect(f.features[0].label).toBe('Gross revenue');
  });

  it('notices that the endpoint answered about a different target', () => {
    // weekly_quantity was requested; units came back. A page that printed
    // only what it got would hide a substitution the reader did not make.
    const f = adaptFeatures(featuresFixture);
    expect(f.targetRequested).toBe('weekly_quantity');
    expect(f.target).toBe('units');
    expect(f.targetSubstituted).toBe(true);
  });

  it('does not treat a substitution as present when the targets match', () => {
    const f = adaptFeatures({ target: 'units', target_requested: 'units', features: [] });
    expect(f.targetSubstituted).toBe(false);
  });

  it('keeps model importance as null rather than as an empty result', () => {
    const f = adaptFeatures(featuresFixture);
    expect(f.modelImportance).toBeNull();
    expect(f.limitations).toHaveLength(5);
  });

  it('records that the whole population was used, not a sample', () => {
    const f = adaptFeatures(featuresFixture);
    expect(f.sampled).toBe(false);
    expect(f.rowsUsed).toBe(f.rowsAvailable);
  });
});

describe('rankDisagreements', () => {
  it('finds the feature the two estimators most disagree about', () => {
    // avg_unit_price is 4th by kNN and 10th by binned: the kNN estimator is
    // seeing structure the bins hide, which is what the endpoint's own note
    // describes.
    const f = adaptFeatures(featuresFixture);
    const d = rankDisagreements(f.features);
    expect(d[0].key).toBe('avg_unit_price');
    expect(d[0].gap).toBe(6);
  });

  it('ignores a one-place shuffle, which is noise in an ordering of 17', () => {
    const f = adaptFeatures(featuresFixture);
    const d = rankDisagreements(f.features, { minGap: 2 });
    expect(d.map((x) => x.key)).not.toContain('price_ratio');
    expect(d.every((x) => x.gap >= 2)).toBe(true);
  });

  it('returns an empty list when nothing moves', () => {
    expect(rankDisagreements([{ rankKnn: 1, rankBinned: 1 }])).toEqual([]);
  });
});

describe('binRange', () => {
  it('shows how far the binned estimate moves with the bin count', () => {
    // 0.3993 at three bins, 0.7339 at ten. The endpoint reports three counts
    // precisely because the answer depends on the choice.
    const f = adaptFeatures(featuresFixture);
    const r = binRange(f.features[0]);
    expect(r.low).toBeCloseTo(0.3993, 4);
    expect(r.high).toBeCloseTo(0.7339, 4);
    expect(r.spread).toBeCloseTo(0.3346, 4);
  });

  it('is null when no bin breakdown is reported', () => {
    expect(binRange({})).toBeNull();
  });
});
