import { describe, expect, it } from 'vitest';

import { describe as describeFilters, fromSearchParams, toQuery, toSearchParams } from './filterState.js';

const BOUNDS = { min_date: '2009-12-01', max_date: '2011-12-09' };

describe('fromSearchParams', () => {
  it('falls back to defaults for anything absent', () => {
    expect(fromSearchParams(new URLSearchParams())).toEqual({
      preset: 'all',
      from: '',
      to: '',
      region: '',
      category: '',
    });
  });

  it('ignores a preset it does not recognise', () => {
    // A hand-edited or stale URL must not put the filter bar in a state with
    // no matching option, where the select would show a blank.
    expect(fromSearchParams(new URLSearchParams('preset=last-fortnight')).preset).toBe('all');
  });

  it('treats a custom preset with no dates as no filter at all', () => {
    expect(fromSearchParams(new URLSearchParams('preset=custom')).preset).toBe('all');
  });
});

describe('toSearchParams', () => {
  it('omits defaults so a shared link reads as what was chosen', () => {
    expect(toSearchParams({ preset: 'all', from: '', to: '', region: 'EIRE', category: '' })).toEqual({
      region: 'EIRE',
    });
  });

  it('round-trips through fromSearchParams', () => {
    const state = { preset: 'custom', from: '2011-01-01', to: '2011-06-30', region: '', category: 'Gifts' };
    expect(fromSearchParams(new URLSearchParams(toSearchParams(state)))).toEqual(state);
  });
});

describe('toQuery', () => {
  it('anchors a preset to the last trading day, not to today', () => {
    // This is the whole reason presets are computed rather than taken from
    // the clock: Online Retail II ends in December 2011, so "last 90 days"
    // measured from the current date selects nothing on every dataset here.
    const query = toQuery({ preset: '90d', from: '', to: '', region: '', category: '' }, BOUNDS);
    expect(query.date_to).toBe('2011-12-09');
    expect(query.date_from).toBe('2011-09-11');
  });

  it('never selects earlier than the dataset starts', () => {
    const narrow = { min_date: '2011-11-01', max_date: '2011-12-09' };
    const query = toQuery({ preset: '12m', from: '', to: '', region: '', category: '' }, narrow);
    expect(query.date_from).toBe('2011-11-01');
  });

  it('leaves the range open when the bounds are not loaded yet', () => {
    const query = toQuery({ preset: '30d', from: '', to: '', region: '', category: '' }, null);
    expect(query.date_from).toBeUndefined();
    expect(query.date_to).toBeUndefined();
  });

  it('passes a custom range through unchanged', () => {
    const query = toQuery(
      { preset: 'custom', from: '2010-03-01', to: '2010-04-01', region: 'EIRE', category: '' },
      BOUNDS,
    );
    expect(query).toEqual({ region: 'EIRE', date_from: '2010-03-01', date_to: '2010-04-01' });
  });

  it('sends no date keys at all for the full dataset', () => {
    expect(toQuery({ preset: 'all', from: '', to: '', region: '', category: '' }, BOUNDS)).toEqual({});
  });
});

describe('describe', () => {
  it('says which date the preset counted back from', () => {
    const text = describeFilters({ preset: '30d', from: '', to: '', region: '', category: '' }, BOUNDS);
    expect(text).toContain('2011-12-09');
    expect(text).toContain('last trading day');
  });

  it('does not claim an anchor for a custom range', () => {
    const text = describeFilters(
      { preset: 'custom', from: '2011-01-01', to: '2011-02-01', region: '', category: '' },
      BOUNDS,
    );
    expect(text).not.toContain('last trading day');
  });
});
