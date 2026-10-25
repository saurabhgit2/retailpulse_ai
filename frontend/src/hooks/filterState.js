/**
 * Filter state, as pure functions.
 *
 * The hook below is five lines of React around these; the rules are here so
 * they can be tested without a router.
 *
 * One decision worth defending: **presets are anchored to the dataset's own
 * last trading day, not to today.** Online Retail II ends on 9 December 2011.
 * A "last 90 days" preset measured from the current date returns an empty
 * chart on every dataset in this project, and the reader has no way to tell
 * an empty filter from an empty result. Anchoring to the data means the
 * preset always selects something, and the filter bar says which date it
 * counted back from.
 */

export const PRESETS = [
  { key: 'all', label: 'All data' },
  { key: '30d', label: 'Last 30 days', days: 30 },
  { key: '90d', label: 'Last 90 days', days: 90 },
  { key: '12m', label: 'Last 12 months', days: 365 },
  { key: 'custom', label: 'Custom range' },
];

export const EMPTY = { preset: 'all', from: '', to: '', region: '', category: '' };

const KEYS = Object.keys(EMPTY);

/** Read filters out of a URLSearchParams, falling back to the defaults. */
export function fromSearchParams(params) {
  const read = (k) => params.get(k) ?? '';
  const state = { ...EMPTY };
  for (const key of KEYS) {
    const value = read(key);
    if (value) state[key] = value;
  }
  if (!PRESETS.some((p) => p.key === state.preset)) state.preset = 'all';
  // A custom preset with no dates is indistinguishable from "all" and would
  // leave the date inputs showing a range the data does not have.
  if (state.preset === 'custom' && !state.from && !state.to) state.preset = 'all';
  return state;
}

/**
 * Write filters into a plain object for the URL, omitting defaults.
 *
 * Omitting them keeps the address bar readable and, more usefully, makes a
 * shared link mean "the dashboard with these filters" rather than carrying
 * five empty parameters that look deliberate.
 */
export function toSearchParams(state) {
  const out = {};
  for (const key of KEYS) {
    if (state[key] && state[key] !== EMPTY[key]) out[key] = state[key];
  }
  return out;
}

const DAY = 24 * 60 * 60 * 1000;

/** `YYYY-MM-DD` for a Date, in UTC, matching the dataset's own calendar. */
export function isoDay(date) {
  return new Date(date).toISOString().slice(0, 10);
}

/**
 * Turn filter state into the query the analytics endpoints take.
 *
 * `bounds` is the dataset's own `{ min_date, max_date }` from
 * `/filter-options`. Without it a preset cannot be resolved, so the range is
 * left open rather than guessed.
 */
export function toQuery(state, bounds) {
  const query = {};
  if (state.region) query.region = state.region;
  if (state.category) query.category = state.category;

  if (state.preset === 'custom') {
    if (state.from) query.date_from = state.from;
    if (state.to) query.date_to = state.to;
    return query;
  }

  const preset = PRESETS.find((p) => p.key === state.preset);
  if (!preset?.days || !bounds?.max_date) return query;

  const end = new Date(bounds.max_date);
  if (Number.isNaN(end.getTime())) return query;
  const start = new Date(end.getTime() - (preset.days - 1) * DAY);
  const floor = bounds.min_date ? new Date(bounds.min_date) : null;
  query.date_from = isoDay(floor && start < floor ? floor : start);
  query.date_to = isoDay(end);
  return query;
}

/** The sentence under the filter bar that says what is actually selected. */
export function describe(state, bounds) {
  const query = toQuery(state, bounds);
  const parts = [];
  if (query.date_from || query.date_to) {
    parts.push(`${query.date_from ?? 'start'} to ${query.date_to ?? 'end'}`);
  } else {
    parts.push('all dates');
  }
  if (state.region) parts.push(state.region);
  if (state.category) parts.push(state.category);
  const anchored =
    state.preset !== 'all' && state.preset !== 'custom' && bounds?.max_date
      ? ` (counted back from the last trading day, ${isoDay(bounds.max_date)})`
      : '';
  return `Showing ${parts.join(' · ')}${anchored}.`;
}
