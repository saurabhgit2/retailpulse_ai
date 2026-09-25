/**
 * MOCK ONLY. A simplified, in-browser version of the cleaning pipeline
 * (architecture §12.3), so the data-quality report screen can be built and
 * tested before the backend exists.
 *
 * Differences from the real pipeline, stated in the report itself:
 *  - it only sees the preview rows read in the browser, not the whole file;
 *  - it implements 9 of the 12 steps (no description canonicalisation,
 *    no per-product outliers, no closure-calendar detection).
 *
 * It follows the same rules as the real pipeline: every step returns a record
 * of what it did, and the row counts must add up (the conservation check).
 */
import { parseDate } from '../../utils/dates';
import { computeCapabilities } from '../../utils/capabilities';
import { FIELD_GUIDE } from './fixtures';

export const MOCK_PIPELINE_VERSION = 'mock-0.1';

function makeAccessor(header, mapping) {
  const index = {};
  Object.entries(mapping).forEach(([field, column]) => {
    if (column) index[field] = header.indexOf(column);
  });
  const get = (row, field) => (index[field] === undefined ? undefined : (row[index[field]] ?? '').trim());
  const toObject = (row) =>
    Object.fromEntries(Object.keys(index).map((field) => [field, get(row, field)]));
  return { get, toObject, has: (field) => index[field] !== undefined };
}

function median(values) {
  const sorted = [...values].sort((a, b) => a - b);
  const mid = Math.floor(sorted.length / 2);
  return sorted.length % 2 ? sorted[mid] : (sorted[mid - 1] + sorted[mid]) / 2;
}

/**
 * Run the mock pipeline.
 * @returns {{ report: object, rowsClean: number, dateMin: string|null, dateMax: string|null }}
 */
export function runMockPipeline({ header, rows, mapping, options, fileTruncated }) {
  const { get, toObject, has } = makeAccessor(header, mapping);
  const actions = [];
  const excludedByReason = {};
  let current = rows;

  // Each exclusion step filters `current` and records exactly what it removed.
  // The predicate runs exactly once per row: some predicates remember what they
  // have seen (the duplicate check), so running them twice would give wrong results.
  const exclude = (step, title, rationale, predicate) => {
    const kept = [];
    const removed = [];
    current.forEach((row) => (predicate(row) ? removed : kept).push(row));
    const rowsBefore = current.length;
    current = kept;
    excludedByReason[step] = removed.length;
    actions.push({
      step,
      title,
      kind: 'excluded',
      rows_before: rowsBefore,
      rows_after: current.length,
      rows_affected: removed.length,
      rationale,
      examples: removed.slice(0, 3).map(toObject),
    });
  };
  // Flag steps count rows but keep them.
  const flag = (step, title, rationale, predicate, kind = 'flagged') => {
    const matched = current.filter(predicate);
    actions.push({
      step,
      title,
      kind,
      rows_before: current.length,
      rows_after: current.length,
      rows_affected: matched.length,
      rationale,
      examples: matched.slice(0, 3).map(toObject),
    });
    return matched;
  };

  const numericFields = ['quantity', 'unit_price', 'revenue'].filter(has);
  const dateFormat = options.date_format;

  // 1. Parse types
  exclude(
    'invalid_value',
    'Excluded rows with an unreadable date or number',
    `Dates are read as "${dateFormat}". A row whose date or ${numericFields.join('/') || 'numbers'} cannot be read cannot be placed in time or valued.`,
    (row) =>
      parseDate(get(row, 'occurred_at'), dateFormat) === null ||
      numericFields.some((f) => get(row, f) !== '' && !Number.isFinite(Number(get(row, f)))),
  );

  // 2. Exact duplicates
  if (options.drop_exact_duplicates) {
    const seen = new Set();
    exclude(
      'exact_duplicate',
      'Removed exact duplicate rows',
      'Rows identical in every column are treated as double entries. Caveat: some may be genuine repeat scans. This assumption is listed as a limitation.',
      (row) => {
        const key = row.join('\u001f'); // a separator that never appears in CSV text
        if (seen.has(key)) return true;
        seen.add(key);
        return false;
      },
    );
  }

  // 3. Non-merchandise lines
  if (has('product_code') && options.exclude_non_product_codes) {
    const codes = new Set((options.non_product_codes ?? []).map((c) => c.toUpperCase()));
    exclude(
      'non_product_code',
      'Excluded fee and adjustment lines',
      'Postage, bank charges, fees and manual adjustments are not product sales and would distort product and demand analysis.',
      (row) => codes.has(get(row, 'product_code').toUpperCase()),
    );
  }

  // 4. Invalid prices
  if (has('unit_price')) {
    exclude(
      'non_positive_price',
      'Excluded lines with a zero or negative price',
      'Zero-price lines are free items or adjustments; negative prices are write-offs. Neither is a sale.',
      (row) => Number(get(row, 'unit_price')) <= 0,
    );
  }

  // 5. Returns: flagged, not deleted
  const returns = flag(
    'returns_flagged',
    'Flagged returns and cancellations (kept)',
    'Returns reduce net revenue, so they are kept and flagged. Demand forecasting and basket analysis leave them out.',
    (row) =>
      (has('invoice_id') && get(row, 'invoice_id').toUpperCase().startsWith('C')) ||
      (has('quantity') && Number(get(row, 'quantity')) < 0),
  );

  // 6. Missing customer IDs: kept as guests
  let guests = [];
  if (has('customer_id')) {
    guests = flag(
      'missing_customer_id',
      'Kept rows without a customer ID as guest sales',
      'These are still valid sales for revenue and forecasting, but cannot be used for customer segmentation.',
      (row) => get(row, 'customer_id') === '',
    );
  }

  // 7. Revenue derivation
  if (!has('revenue') && has('quantity') && has('unit_price')) {
    flag(
      'revenue_derived',
      'Calculated revenue as quantity × unit price',
      'The file has no revenue column. The derivation is recorded so every revenue figure can be traced back.',
      () => true,
      'transformed',
    );
  }

  // 8. Outliers: flagged with a robust z-score (median and MAD resist outliers)
  if (has('quantity') && current.length > 10) {
    const quantities = current.map((row) => Math.abs(Number(get(row, 'quantity'))));
    const med = median(quantities);
    const mad = median(quantities.map((q) => Math.abs(q - med))) || 1;
    const threshold = options.outlier_threshold ?? 5;
    flag(
      'outlier_flagged',
      `Flagged unusually large quantities (robust z > ${threshold})`,
      'Flagged, not removed: large wholesale orders are real. Each analysis decides whether to exclude them. (Mock: computed across all products; the backend does it per product.)',
      (row) => (0.6745 * (Math.abs(Number(get(row, 'quantity'))) - med)) / mad > threshold,
    );
  }

  // 9. Partial final period
  const times = current
    .map((row) => parseDate(get(row, 'occurred_at'), dateFormat))
    .filter(Boolean)
    .map((d) => d.getTime());
  const dateMin = times.length ? new Date(Math.min(...times)).toISOString() : null;
  const dateMax = times.length ? new Date(Math.max(...times)).toISOString() : null;
  const warnings = [];
  if (dateMax && new Date(dateMax).getUTCDay() !== 0) {
    warnings.push({
      code: 'PARTIAL_FINAL_WEEK',
      message: `The data ends on ${dateMax.slice(0, 10)}, part-way through a week. That week will be excluded from growth rates and model training.`,
    });
  }
  if (fileTruncated) {
    warnings.push({
      code: 'MOCK_PREVIEW_ONLY',
      message: `Mock mode examined only the first ${rows.length.toLocaleString()} rows read in your browser. The backend processes the whole file.`,
    });
  }

  const rowsExcluded = Object.values(excludedByReason).reduce((a, b) => a + b, 0);
  const rowsClean = current.length;

  const report = {
    pipeline_version: MOCK_PIPELINE_VERSION,
    scope: {
      mode: 'mock_preview',
      rows_examined: rows.length,
      file_truncated: fileTruncated,
      note: 'Generated by the in-browser mock API from preview rows. Not a result of the real pipeline.',
    },
    summary: {
      rows_raw: rows.length,
      rows_clean: rowsClean,
      rows_excluded: rowsExcluded,
      rows_returns_flagged: returns.length,
      rows_guest: guests.length,
    },
    conservation: {
      ok: rows.length === rowsClean + rowsExcluded,
      rows_raw: rows.length,
      rows_clean: rowsClean,
      rows_excluded: rowsExcluded,
    },
    excluded_by_reason: excludedByReason,
    actions,
    warnings,
    date_range: { min: dateMin, max: dateMax },
    capabilities: computeCapabilities(mapping, FIELD_GUIDE.capabilities),
  };

  return { report, rowsClean, dateMin, dateMax };
}
