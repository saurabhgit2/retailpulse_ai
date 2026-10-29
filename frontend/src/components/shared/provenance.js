/**
 * Where a cached analytics response came from, and what it cost.
 *
 * Shown on the page because a cached result and a freshly computed one are
 * not the same claim: a cache hit is as old as the computation behind it, and
 * on a dataset that can be re-ingested that is worth being able to see. It
 * also makes the cost visible — several of these endpoints take seconds, and
 * a reader who knows that reads a slow page as expensive rather than broken.
 */

const num = (value) => (typeof value === 'number' && Number.isFinite(value) ? value : null);

export function cacheNote(payload) {
  const cache = payload?._cache;
  if (!cache) return null;
  const ms = num(cache.computed_ms);
  const seconds = ms === null ? null : (ms / 1000).toFixed(1);
  if (cache.hit) {
    return seconds
      ? `Served from cache, originally computed in ${seconds}s.`
      : 'Served from cache.';
  }
  return seconds ? `Computed for this request in ${seconds}s.` : null;
}
