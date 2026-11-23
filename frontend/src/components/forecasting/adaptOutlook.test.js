import { describe, expect, it } from 'vitest';

import OUTLOOK from './outlook.fixture.json';
import { adaptOutlook, errorPhrase, measureView, productRows } from './adaptOutlook.js';

/**
 * `outlook.fixture.json` is a response from GET /forecast/outlook, captured on
 * the test suite's SYNTHETIC dataset and trimmed. Fixturing from the server is
 * the point: this file and the adapter are the only places the frontend knows
 * the response's field names.
 */

const revenue = OUTLOOK.measures.net_revenue;

describe('measureView', () => {
  it('puts the actuals and the forecast on one time axis', () => {
    const view = measureView(revenue);
    const h = revenue.history.periods.length;
    const f = revenue.forecast.periods.length;
    expect(view.chart.x).toHaveLength(h + f);
    expect(view.chart.x[h]).toBe(revenue.forecast.periods[0]);
    expect(view.chart.firstForecastIndex).toBe(h);
  });

  it('leaves the forecast empty over the history except where the two lines join', () => {
    const view = measureView(revenue);
    const h = revenue.history.periods.length;
    expect(view.chart.point.slice(0, h - 1).every((v) => v === null)).toBe(true);
    expect(view.chart.point[h - 1]).toBe(revenue.history.values[h - 1]);
    expect(view.chart.actual.slice(h).every((v) => v === null)).toBe(true);
  });

  it('carries the chosen model and its accuracy', () => {
    const view = measureView(revenue);
    expect(view.model.name).toBe(revenue.model.name);
    expect(view.accuracy.wape).toBeCloseTo(revenue.accuracy.wape, 6);
    expect(view.candidates.filter((c) => c.chosen)).toHaveLength(1);
  });

  it('marks the flat methods so the page can say so', () => {
    const flat = measureView(revenue).candidates.filter((c) => c.flat).map((c) => c.name);
    expect(flat).toEqual(expect.arrayContaining(['recent_level', 'recent_average']));
  });

  it('leaves a likely-closed week out of the line instead of drawing a plunge to zero', () => {
    const closed = structuredClone(revenue);
    closed.forecast.likely_closed[2] = true;
    closed.forecast.point[2] = 0;
    const view = measureView(closed);
    const h = closed.history.periods.length;
    expect(view.chart.point[h + 2]).toBeNull();
    expect(view.weeks[2].closed).toBe(true);
    expect(view.closedWeeks).toEqual([closed.forecast.periods[2]]);
  });

  it('passes an unavailable measure through with its reason', () => {
    const view = measureView({ available: false, label: 'Units sold', reason: 'too short' });
    expect(view).toEqual({ available: false, label: 'Units sold', reason: 'too short' });
  });
});

describe('productRows', () => {
  it('keeps the server’s revenue order and labels each product', () => {
    const rows = productRows(OUTLOOK.products);
    expect(rows.map((r) => r.code)).toEqual(OUTLOOK.products.rows.map((r) => r.product_code));
    expect(rows[0].description).toMatch(/^SYNTHETIC/);
    expect(rows[0].nextHorizon).toBeCloseTo(OUTLOOK.products.rows[0].next_horizon_units, 6);
  });

  it('gives each product a chartable view of its own', () => {
    const [row] = productRows(OUTLOOK.products);
    expect(row.view.available).toBe(true);
    expect(row.view.chart.x.length).toBeGreaterThan(row.view.chart.firstForecastIndex);
  });

  it('returns nothing when the block is unavailable', () => {
    expect(productRows({ available: false })).toEqual([]);
    expect(productRows(null)).toEqual([]);
  });
});

describe('errorPhrase', () => {
  it('reads a typical error in plain words', () => {
    expect(errorPhrase(8.6)).toBe('usually within 9%');
    expect(errorPhrase(0.2)).toBe('usually within 1%');
    expect(errorPhrase(null)).toBe('accuracy unknown');
  });
});

describe('adaptOutlook', () => {
  it('shapes both measures and the products in one call', () => {
    const view = adaptOutlook(OUTLOOK);
    expect(view.available).toBe(true);
    expect(view.measures.net_revenue.available).toBe(true);
    expect(view.measures.net_units.available).toBe(true);
    expect(view.lastPeriod).toBe(OUTLOOK.series.last_period);
    expect(view.products.length).toBe(OUTLOOK.products.rows.length);
  });

  it('returns null for no response', () => {
    expect(adaptOutlook(null)).toBeNull();
  });
});
