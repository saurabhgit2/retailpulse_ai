import { describe, expect, it } from 'vitest';

import {
  boundsOf,
  describe as describeFilters,
  fromSearchParams,
  toQuery,
  toSearchParams,
} from './filterState.js';

const OPTIONS = { date_min: '2009-12-01', date_max: '2011-12-09', rows: 1_021_349 };
const BOUNDS = boundsOf(OPTIONS);
const base = (over = {}) => ({
  preset: 'all',
  from: '',
  to: '',
  region: '',
  category: '',
  customers: '',
  returns: '',
  ...over,
});

describe('boundsOf', () => {
  it('reads the flat date_min and date_max the server sends', () => {
    expect(BOUNDS).toEqual({ min: '2009-12-01', max: '2011-12-09' });
  });

  it('is null before the options have loaded', () => {
    expect(boundsOf(null)).toBeNull();
    expect(boundsOf({ rows: 0 })).toBeNull();
  });
});

describe('fromSearchParams', () => {
  it('falls back to defaults for anything absent', () => {
    expect(fromSearchParams(new URLSearchParams())).toEqual(base());
  });

  it('ignores a preset it does not recognise', () => {
    // A hand-edited or stale URL must not put the filter bar in a state with
    // no matching option, where the select would render blank.
    expect(fromSearchParams(new URLSearchParams('preset=last-fortnight')).preset).toBe('all');
  });

  it('ignores a customer type the API does not accept', () => {
    // The enum is all / registered / guest; anything else would be a 422.
    expect(fromSearchParams(new URLSearchParams('customers=vip')).customers).toBe('');
  });

  it('treats a custom preset with no dates as no filter at all', () => {
    expect(fromSearchParams(new URLSearchParams('preset=custom')).preset).toBe('all');
  });
});

describe('toSearchParams', () => {
  it('omits defaults so a shared link reads as what was chosen', () => {
    expect(toSearchParams(base({ region: 'EIRE' }))).toEqual({ region: 'EIRE' });
  });

  it('round-trips through fromSearchParams', () => {
    const state = base({ preset: 'custom', from: '2011-01-01', to: '2011-06-30', customers: 'guest' });
    expect(fromSearchParams(new URLSearchParams(toSearchParams(state)))).toEqual(state);
  });
});

describe('toQuery', () => {
  it('sends the plural, repeatable keys the API documents', () => {
    // The server reads regions and categories into list[str]; a bare string
    // would arrive as a one-character-per-item list or a 422.
    const query = toQuery(base({ region: 'EIRE', category: 'Gifts' }), BOUNDS);
    expect(query.regions).toEqual(['EIRE']);
    expect(query.categories).toEqual(['Gifts']);
  });

  it('anchors a preset to the last trading day, not to today', () => {
    // The whole reason presets are computed rather than taken from the
    // clock: Online Retail II ends in December 2011, so "last 90 days"
    // measured from the current date selects nothing on every dataset here.
    const query = toQuery(base({ preset: '90d' }), BOUNDS);
    expect(query.date_to).toBe('2011-12-09');
    expect(query.date_from).toBe('2011-09-11');
  });

  it('never selects earlier than the dataset starts', () => {
    const narrow = boundsOf({ date_min: '2011-11-01', date_max: '2011-12-09' });
    expect(toQuery(base({ preset: '12m' }), narrow).date_from).toBe('2011-11-01');
  });

  it('leaves the range open when the bounds are not loaded yet', () => {
    const query = toQuery(base({ preset: '30d' }), null);
    expect(query.date_from).toBeUndefined();
    expect(query.date_to).toBeUndefined();
  });

  it('passes a custom range through unchanged', () => {
    const query = toQuery(base({ preset: 'custom', from: '2010-03-01', to: '2010-04-01' }), BOUNDS);
    expect(query).toEqual({ date_from: '2010-03-01', date_to: '2010-04-01' });
  });

  it('sends include_returns only when the reader excludes them', () => {
    // Omitting it lets the server's documented default stand instead of this
    // file restating it and drifting if it changes.
    expect(toQuery(base(), BOUNDS).include_returns).toBeUndefined();
    expect(toQuery(base({ returns: 'exclude' }), BOUNDS).include_returns).toBe(false);
  });

  it('sends no date keys at all for the full dataset', () => {
    expect(toQuery(base(), BOUNDS)).toEqual({});
  });
});

describe('describe', () => {
  it('says which date the preset counted back from', () => {
    const text = describeFilters(base({ preset: '30d' }), BOUNDS);
    expect(text).toContain('2011-12-09');
    expect(text).toContain('last trading day');
  });

  it('does not claim an anchor for a custom range', () => {
    const text = describeFilters(base({ preset: 'custom', from: '2011-01-01', to: '2011-02-01' }), BOUNDS);
    expect(text).not.toContain('last trading day');
  });
});
