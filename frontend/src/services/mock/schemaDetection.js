/**
 * MOCK ONLY. Imitates the backend's column detection
 * (backend/app/preprocessing/schema_detection.py, built in Phase 3) so the upload
 * wizard can be developed before the backend exists. The algorithm is the one
 * described in architecture §12.1:
 *   1. normalise each header and look it up in the synonym list;
 *   2. check the column's content agrees with the expected type;
 *   3. never guess when it is ambiguous. Report it instead.
 */
import { FIELD_GUIDE } from './fixtures';
import { detectDateFormats } from '../../utils/dates';
import { computeCapabilities } from '../../utils/capabilities';

/** "Customer ID" -> "customerid", "Invoice_Date" -> "invoicedate" */
export function normaliseHeader(name) {
  return String(name ?? '')
    .toLowerCase()
    .replace(/[^a-z0-9]/g, '');
}

function isNumeric(value) {
  return value !== '' && Number.isFinite(Number(value));
}

function firstDistinct(values, count) {
  return [...new Set(values)].slice(0, count);
}

/** Describe each column from the preview rows. */
export function profileColumns(header, rows) {
  return header.map((name, index) => {
    const values = rows.map((row) => (row[index] ?? '').trim());
    const nonEmpty = values.filter((v) => v !== '');
    const numericShare = nonEmpty.length ? nonEmpty.filter(isNumeric).length / nonEmpty.length : 0;
    const dates = detectDateFormats(nonEmpty.slice(0, 1000));

    let inferredType = 'text';
    if (dates.candidates.length > 0) inferredType = 'datetime';
    else if (nonEmpty.length > 0 && numericShare >= 0.95) inferredType = 'numeric';

    return {
      name,
      inferred_type: inferredType,
      null_count_sample: values.length - nonEmpty.length,
      distinct_count_sample: new Set(nonEmpty).size,
      sample_values: firstDistinct(nonEmpty, 3),
      date_format_candidates: dates.candidates,
      date_ambiguous: dates.ambiguous,
    };
  });
}

function typeMatches(field, column) {
  if (field.expected_type === 'any') return true;
  return field.expected_type === column.inferred_type;
}

/**
 * Suggest a source column for each canonical field.
 * @returns {{ mapping: Record<string, string|null>, warnings: object[] }}
 */
export function suggestMapping(columns, fields = FIELD_GUIDE.fields) {
  const mapping = Object.fromEntries(fields.map((f) => [f.key, null]));
  const used = new Set();
  const warnings = [];

  fields.forEach((field) => {
    const match = columns.find(
      (c) => !used.has(c.name) && field.synonyms.includes(normaliseHeader(c.name)),
    );
    if (!match) return;
    if (!typeMatches(field, match)) {
      warnings.push({
        code: 'TYPE_MISMATCH',
        message: `"${match.name}" looks like ${field.label}, but its values are ${match.inferred_type}, not ${field.expected_type}. It was left unmapped; map it yourself if it is correct.`,
      });
      return;
    }
    mapping[field.key] = match.name;
    used.add(match.name);
  });

  return { mapping, warnings };
}

/** Everything the upload endpoint returns about a new file. */
export function buildUploadProfile(header, rows, { truncated }) {
  const columns = profileColumns(header, rows);
  const { mapping, warnings } = suggestMapping(columns);

  if (!mapping.revenue && mapping.quantity && mapping.unit_price) {
    warnings.push({
      code: 'REVENUE_WILL_BE_DERIVED',
      message: 'No revenue column found. Revenue will be calculated as quantity × unit price.',
    });
  }
  if (!mapping.customer_id) {
    warnings.push({
      code: 'NO_CUSTOMER_ID',
      message: 'No customer ID column found. Customer segmentation will be unavailable.',
    });
  }
  if (!mapping.category) {
    warnings.push({
      code: 'NO_CATEGORY',
      message: 'No category column found. Category analyses will be hidden.',
    });
  }
  const dateColumn = columns.find((c) => c.name === mapping.occurred_at);
  if (dateColumn?.date_ambiguous) {
    warnings.push({
      code: 'AMBIGUOUS_DATE_FORMAT',
      message: `Dates in "${dateColumn.name}" could be day/month or month/day. Choose the correct format before processing.`,
    });
  }

  const missingRequired = FIELD_GUIDE.fields
    .filter((f) => f.status === 'required' && !mapping[f.key])
    .map((f) => f.key);

  return {
    detected_columns: columns,
    suggested_mapping: mapping,
    missing_required: missingRequired,
    warnings,
    capabilities_preview: computeCapabilities(mapping, FIELD_GUIDE.capabilities),
    preview: { rows_examined: rows.length, file_truncated: truncated },
  };
}
