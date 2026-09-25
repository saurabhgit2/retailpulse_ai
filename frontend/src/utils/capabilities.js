/**
 * Work out which analysis modules a dataset can support from its column
 * mapping. The rules come from the backend's field guide, so the frontend holds
 * no hard-coded business rules; it only evaluates them.
 *
 * A capability definition looks like:
 *   { key: 'segmentation', label: 'Customer segmentation',
 *     requires_all: ['customer_id', 'invoice_id', 'occurred_at'],
 *     requires_one_of: [['revenue'], ['quantity', 'unit_price']] }
 *
 * requires_one_of means "at least one of these groups must be fully mapped".
 */

function isMapped(mapping, field) {
  return Boolean(mapping?.[field]);
}

/**
 * @returns {Array<{ key, label, enabled, missing: string[] }>}
 *          `missing` lists what to map to enable the capability.
 */
export function computeCapabilities(mapping, definitions = []) {
  return definitions.map((definition) => {
    const missingAll = (definition.requires_all ?? []).filter((f) => !isMapped(mapping, f));

    let missingOneOf = [];
    const groups = definition.requires_one_of ?? [];
    if (groups.length > 0) {
      const satisfied = groups.some((group) => group.every((f) => isMapped(mapping, f)));
      if (!satisfied) missingOneOf = [groups.map((group) => group.join(' + ')).join(' or ')];
    }

    const missing = [...missingAll, ...missingOneOf];
    return { key: definition.key, label: definition.label, enabled: missing.length === 0, missing };
  });
}

/** Source columns that are mapped to more than one field (not allowed). */
export function findDuplicateSources(mapping) {
  const seen = new Map();
  const duplicates = new Set();
  Object.entries(mapping ?? {}).forEach(([field, column]) => {
    if (!column) return;
    if (seen.has(column)) {
      duplicates.add(column);
    } else {
      seen.set(column, field);
    }
  });
  return [...duplicates];
}

/** Required fields (from the field guide) that have no source column yet. */
export function findMissingRequired(mapping, fields = []) {
  return fields.filter((f) => f.status === 'required' && !isMapped(mapping, f.key)).map((f) => f.key);
}
