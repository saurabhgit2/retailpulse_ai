import { DATE_FORMATS } from '../../utils/dates';

/**
 * Lets the user choose how dates are read when more than one format fits.
 * A radio group (not a select) so all the options, with examples, are visible
 * at once.
 */
export function DateFormatPicker({ candidates, value, onChange }) {
  if (!candidates || candidates.length === 0) {
    return <p className="text-sm text-crit">No readable dates were found in the mapped date column.</p>;
  }
  if (candidates.length === 1) {
    return (
      <p className="text-sm text-ink-2">
        Dates will be read as <strong className="text-ink">{DATE_FORMATS[candidates[0]].label}</strong>.
      </p>
    );
  }
  return (
    <fieldset className="rounded-lg border border-warn bg-warn-soft px-4 py-3">
      <legend className="px-1 text-sm font-semibold text-warn">Choose the date format</legend>
      <p className="text-sm text-ink-2">
        Your dates fit more than one format (for example, 03/04 could be 3 April or 4 March). Pick the one your
        system uses.
      </p>
      <div className="mt-3 flex flex-col gap-2">
        {candidates.map((key) => (
          <label key={key} className="flex items-center gap-2 text-sm text-ink">
            <input
              type="radio"
              name="date-format"
              value={key}
              checked={value === key}
              onChange={() => onChange(key)}
            />
            {DATE_FORMATS[key].label}
          </label>
        ))}
      </div>
    </fieldset>
  );
}
