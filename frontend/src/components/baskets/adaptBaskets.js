/**
 * The basket-size response, turned into what the Baskets page draws.
 *
 * The generic part of this job — labelling bins, counting the gaps a log
 * axis opens, checking a histogram accounts for every observation — is shared
 * with `/analytics/distributions` and lives in `../shared/histogramShape.js`.
 * It is re-exported here so this module stays the single import for the
 * Baskets page and its tests.
 *
 * What remains below is what is specific to baskets: which fields the
 * endpoint reports, which of them are whole-numbered, and the endpoint's own
 * interpretation.
 */

import {
  distributionShape,
  dominantBinShare,
  edgeText,
  histogramBins,
  histogramCoverage,
  interiorGaps,
  percentileRows,
} from '../shared/histogramShape.js';
import { cacheNote } from '../shared/provenance.js';

export {
  cacheNote,
  dominantBinShare,
  edgeText,
  histogramBins,
  histogramCoverage,
  interiorGaps,
  percentileRows,
};

const num = (value) => (typeof value === 'number' && Number.isFinite(value) ? value : null);

/** Fields the endpoint reports a distribution for, in the order shown. */
export const BASKET_FIELDS = [
  {
    key: 'distinct_items_per_invoice',
    label: 'Distinct items per invoice',
    short: 'Distinct items',
    currency: null,
    unit: 'items',
    // Whole-number valued. This is what licenses the explanation the page
    // gives for empty bins on a log axis, and it is false for order value,
    // so it is recorded per field rather than assumed for both.
    integer: true,
  },
  {
    key: 'order_value',
    label: 'Order value',
    short: 'Order value',
    currency: '£',
    unit: 'value',
    integer: false,
  },
];

/** Top-level figures and the endpoint's own interpretation. */
export function adaptBaskets(payload) {
  const d = payload ?? {};
  return {
    available: d.available !== false,
    invoices: num(d.invoices),
    interpretation: typeof d.interpretation === 'string' ? d.interpretation : null,
  };
}

/** One field's distribution, with both histograms prepared. */
export function adaptField(payload, fieldKey) {
  const meta = BASKET_FIELDS.find((f) => f.key === fieldKey) ?? {
    key: fieldKey,
    label: fieldKey,
    short: fieldKey,
    currency: null,
    integer: false,
  };
  const shape = distributionShape(payload?.[fieldKey], {
    currency: meta.currency,
    integer: meta.integer,
  });
  if (!shape) return null;
  return { ...meta, ...shape };
}
