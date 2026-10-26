import { describe, expect, it } from 'vitest';

import {
  adaptConcentration,
  adaptFilterOptions,
  adaptKpis,
  adaptRanked,
  adaptRates,
  adaptTrend,
  shapeProblem,
} from './adapt.js';

/**
 * The fixtures below are real responses from the running API, trimmed to
 * the first rows. That is the point of them: this file is the only place
 * that knows the server's field names, so the fixtures have to come from
 * the server rather than from what the page would find convenient.
 */

const TRENDS = {
  granularity: 'week',
  ma_window: 4,
  headline: 'gross_revenue',
  points: [
    {
      period: '2009-11-30',
      is_partial: false,
      gross_revenue: 260808.77,
      net_revenue: 254462.21,
      units: 144924,
      orders: 548,
      moving_average: null,
      growth: null,
    },
    {
      period: '2009-12-07',
      is_partial: false,
      gross_revenue: 234033.21,
      net_revenue: 225138.87,
      units: 116251,
      orders: 525,
      moving_average: null,
      growth: -0.10266357224107149,
    },
  ],
};

const PRODUCTS = {
  key: 'product_code',
  sort: 'gross_revenue',
  descending: true,
  entities: 4748,
  total: 19646574.84,
  items: [
    {
      rank: 1,
      key: '22423',
      share: 0.016826867924424428,
      cumulative_share: 0.016826867924424428,
      label: 'REGENCY CAKESTAND 3 TIER',
      gross_revenue: 330590.32,
      net_revenue: 314045.02,
      units: 26478,
      orders: 3918,
    },
    {
      rank: 2,
      key: '85123A',
      share: 0.013293346658485536,
      cumulative_share: 0.030120214582909963,
      label: 'WHITE HANGING HEART T-LIGHT HOLDER',
      gross_revenue: 261168.73,
      net_revenue: 251781.63,
      units: 94719,
      orders: 5464,
    },
  ],
};

const KPIS = {
  values: {
    gross_revenue: 19646574.84,
    returns_value: 804_000,
    net_revenue: 18842574.84,
    units: 10_000_000,
    orders: 39529,
    average_order_value: 476.68,
    active_customers: 5878,
    return_rate: 0.0409,
    guest_revenue_share: 0.164,
    lines: 1021349,
  },
  previous: {},
  growth: { net_revenue: 0.082, orders: -0.031, active_customers: null },
  comparison: { comparable: true, note: null },
};

describe('adaptTrend', () => {
  it('reads the server’s own field names', () => {
    const t = adaptTrend(TRENDS);
    expect(t.x).toEqual(['2009-11-30', '2009-12-07']);
    expect(t.revenue).toEqual([254462.21, 225138.87]);
    expect(t.orders).toEqual([548, 525]);
    expect(t.partial).toEqual([false, false]);
  });

  it('takes net revenue rather than gross', () => {
    // Both are present on every point. Net is the honest headline: it is
    // what the business kept once returns are deducted, and the returns on
    // this dataset are 4% of gross.
    expect(adaptTrend(TRENDS).revenue[0]).toBe(254462.21);
  });

  it('carries a null moving average through rather than dropping to zero', () => {
    // The first points have no moving average because the window has not
    // filled. Zero would draw a line along the axis for a month.
    expect(adaptTrend(TRENDS).movingAverage).toEqual([null, null]);
  });
});

describe('adaptRanked', () => {
  it('reads key, label and net revenue from the items', () => {
    const rows = adaptRanked(PRODUCTS);
    expect(rows[0].key).toBe('22423');
    expect(rows[0].label).toBe('REGENCY CAKESTAND 3 TIER');
    expect(rows[0].value).toBe(314045.02);
    expect(rows[0].share).toBeCloseTo(0.0168, 4);
  });
});

describe('adaptConcentration', () => {
  it('reports the share the returned rows hold, from the last cumulative share', () => {
    const c = adaptConcentration(PRODUCTS);
    expect(c.shown).toBe(2);
    expect(c.topShare).toBeCloseTo(0.0301, 4);
    expect(c.entities).toBe(4748);
    expect(c.total).toBeCloseTo(19646574.84, 2);
  });

  it('claims nothing when there are no rows', () => {
    // The old version looked for a Gini coefficient this endpoint does not
    // return, so the tile sat on an em dash for ever and said nothing about
    // why. Reporting a smaller, supported figure is the fix.
    expect(adaptConcentration({ items: [] }).topShare).toBeNull();
  });
});

describe('adaptKpis', () => {
  it('uses the schema’s field names', () => {
    const byKey = Object.fromEntries(adaptKpis(KPIS).map((f) => [f.key, f]));
    expect(byKey.net_revenue.value).toBe(18842574.84);
    expect(byKey.active_customers.value).toBe(5878);
    expect(byKey.average_order_value.value).toBe(476.68);
  });

  it('keeps a null growth null rather than reading it as no change', () => {
    const byKey = Object.fromEntries(adaptKpis(KPIS).map((f) => [f.key, f]));
    expect(byKey.active_customers.growth).toBeNull();
    expect(byKey.orders.growth).toBeCloseTo(-0.031, 4);
  });

  it('shows the comparison note only when the comparison was refused', () => {
    // comparable: true with a note would otherwise print an explanation
    // beside figures that were in fact compared.
    expect(adaptKpis(KPIS)[0].note).toBeNull();
    const refused = {
      ...KPIS,
      comparison: { comparable: false, note: 'The previous window is shorter.' },
    };
    expect(adaptKpis(refused)[0].note).toBe('The previous window is shorter.');
  });
});

describe('adaptRates', () => {
  it('pulls the rates out of the same payload', () => {
    const r = adaptRates(KPIS);
    expect(r.returnRate).toBeCloseTo(0.0409, 4);
    expect(r.guestShare).toBeCloseTo(0.164, 3);
  });
});

describe('adaptFilterOptions', () => {
  it('flattens the region objects the server sends into names', () => {
    const o = adaptFilterOptions({
      regions: [{ region: 'United Kingdom', rows: 900000 }, { region: 'EIRE', rows: 8000 }],
      categories: ['Gifts'],
      customer_types: ['registered', 'guest'],
      rows: 1021349,
    });
    expect(o.regions).toEqual(['United Kingdom', 'EIRE']);
    expect(o.categories).toEqual(['Gifts']);
  });

  it('survives a response with no regions at all', () => {
    expect(adaptFilterOptions({}).regions).toEqual([]);
  });
});

describe('shapeProblem', () => {
  it('stays quiet when the expected key is present', () => {
    expect(shapeProblem(TRENDS, ['points'])).toBeNull();
  });

  it('names what actually arrived', () => {
    const message = shapeProblem({ granularity: 'week' }, ['points', 'rows']);
    expect(message).toContain('granularity');
  });
});
