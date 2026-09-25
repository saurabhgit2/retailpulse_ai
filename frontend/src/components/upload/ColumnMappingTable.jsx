import { Badge } from '../ui/Badge';

const STATUS_TONE = { required: 'crit', recommended: 'accent', optional: 'neutral' };

/**
 * One row per canonical field, with a <select> to choose the source column.
 *
 * This is a *controlled* component: it holds no state of its own. The parent
 * owns `mapping` and receives every change through onChange(fieldKey, column).
 * That keeps one source of truth, which the parent also uses for validation
 * and the capability preview.
 *
 * A column already used by another field is disabled in the other selects,
 * so the same column can't be mapped twice.
 */
export function ColumnMappingTable({ fields, columns, mapping, onChange }) {
  const usedBy = new Map(
    Object.entries(mapping)
      .filter(([, column]) => column)
      .map(([field, column]) => [column, field]),
  );
  const labelOf = Object.fromEntries(fields.map((f) => [f.key, f.label]));

  return (
    <div className="overflow-x-auto rounded-lg border border-rule">
      <table className="w-full min-w-[40rem] border-collapse text-sm">
        <thead className="bg-surface-2 text-left text-xs tracking-wide text-muted uppercase">
          <tr>
            <th scope="col" className="px-4 py-2 font-medium">RetailPulse field</th>
            <th scope="col" className="px-4 py-2 font-medium">Column in your file</th>
            <th scope="col" className="px-4 py-2 font-medium">Detected values</th>
          </tr>
        </thead>
        <tbody className="bg-surface">
          {fields.map((field) => {
            const selected = mapping[field.key] ?? '';
            const column = columns.find((c) => c.name === selected);
            const missingRequired = field.status === 'required' && !selected;
            const selectId = `map-${field.key}`;
            return (
              <tr key={field.key} className={`border-t border-rule align-top ${missingRequired ? 'bg-crit-soft' : ''}`}>
                <td className="px-4 py-3">
                  <div className="flex flex-wrap items-center gap-2">
                    <label htmlFor={selectId} className="font-medium text-ink">
                      {field.label}
                    </label>
                    <Badge tone={STATUS_TONE[field.status]}>{field.status}</Badge>
                  </div>
                  <p className="mt-1 max-w-sm text-xs text-muted">{field.description}</p>
                </td>
                <td className="px-4 py-3">
                  <select
                    id={selectId}
                    value={selected}
                    onChange={(event) => onChange(field.key, event.target.value || null)}
                    aria-invalid={missingRequired || undefined}
                    className="h-9 w-full min-w-[12rem] rounded-md border border-rule bg-surface px-2 text-sm text-ink"
                  >
                    <option value="">Not mapped</option>
                    {columns.map((c) => {
                      const owner = usedBy.get(c.name);
                      const takenElsewhere = owner && owner !== field.key;
                      return (
                        <option key={c.name} value={c.name} disabled={takenElsewhere}>
                          {c.name}
                          {takenElsewhere ? ` (used for ${labelOf[owner]})` : ''}
                        </option>
                      );
                    })}
                  </select>
                  {missingRequired && <p className="mt-1 text-xs font-medium text-crit">Required: choose a column.</p>}
                </td>
                <td className="px-4 py-3">
                  {column ? (
                    <div className="flex flex-col gap-1">
                      <span className="text-xs text-muted">
                        {column.inferred_type}
                        {column.null_count_sample > 0 && ` · ${column.null_count_sample} empty in preview`}
                      </span>
                      <code className="font-mono text-xs break-all text-ink-2">
                        {column.sample_values.join(' · ') || '(no values)'}
                      </code>
                    </div>
                  ) : (
                    <span className="text-xs text-muted">—</span>
                  )}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
