/**
 * Which colour a series gets.
 *
 * Two rules, both of which are easy to break by accident:
 *
 * 1. **Colour follows the entity, not its rank.** If a filter removes the
 *    second-best product, the third must not inherit its colour. So the slot
 *    is assigned from a stable key and held in a map for the life of the
 *    chart, never from the index of the current array.
 *
 * 2. **There is no ninth colour.** A generated hue is indistinguishable from
 *    an existing slot under colour-vision deficiency, which is exactly the
 *    thing the validated order was chosen to prevent. Past eight, the caller
 *    folds the tail into one "Other" series.
 */

export const SERIES_SLOTS = 8;

export const MUTED = 'var(--series-muted)';

export function slotColor(slot) {
  const index = (((slot % SERIES_SLOTS) + SERIES_SLOTS) % SERIES_SLOTS) + 1;
  return `var(--series-${index})`;
}

/**
 * A colour assigner with a memory.
 *
 * ```js
 * const colors = seriesPalette(['WHITE HANGING HEART', 'REGENCY CAKESTAND']);
 * colors.of('REGENCY CAKESTAND')   // 'var(--series-2)' - and stays slot 2
 * ```
 */
export function seriesPalette(keys = []) {
  const assigned = new Map();
  let next = 0;

  const assign = (key) => {
    if (assigned.has(key)) return assigned.get(key);
    if (next >= SERIES_SLOTS) {
      throw new Error(
        `A ninth series colour was requested for "${key}". The validated ` +
          'palette has eight slots; fold the tail into an "Other" series or ' +
          'use small multiples instead of generating a hue.',
      );
    }
    const color = slotColor(next);
    next += 1;
    assigned.set(key, color);
    return color;
  };

  keys.forEach(assign);

  return {
    of: assign,
    /** Known keys, for a legend, in assignment order. */
    keys: () => Array.from(assigned.keys()),
    size: () => assigned.size,
  };
}

/**
 * Emphasis: one series carries the story, the rest are context.
 *
 * This is the answer to "eight hues when the story is one number". A chart
 * that highlights two lines against six grey ones is read in a second; the
 * same chart in eight colours is read by cross-referencing a legend.
 */
export function emphasisPalette(keys, emphasised) {
  const highlighted = new Set(emphasised);
  const palette = seriesPalette();
  // Assign slots in key order, but only to the emphasised ones, so the first
  // highlighted series is always slot 1 regardless of where it sits.
  keys.filter((k) => highlighted.has(k)).forEach((k) => palette.of(k));
  return {
    of: (key) => (highlighted.has(key) ? palette.of(key) : MUTED),
    isEmphasised: (key) => highlighted.has(key),
  };
}

/**
 * Fold a ranked list down to the palette's capacity.
 * Returns the top `limit - 1` plus one combined row, so nothing is dropped
 * silently and the total still adds up.
 */
export function foldTail(rows, { limit = SERIES_SLOTS, key = 'label', value = 'value' } = {}) {
  if (rows.length <= limit) return { rows: rows.slice(), folded: 0 };
  const head = rows.slice(0, limit - 1);
  const tail = rows.slice(limit - 1);
  const total = tail.reduce((sum, r) => sum + (Number(r[value]) || 0), 0);
  return {
    rows: [...head, { [key]: `Other (${tail.length})`, [value]: total, isOther: true }],
    folded: tail.length,
  };
}
