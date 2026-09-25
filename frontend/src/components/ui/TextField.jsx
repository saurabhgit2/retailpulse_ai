/**
 * A labelled text input. The label is linked to the input with htmlFor/id, and
 * the hint or error text with aria-describedby, so screen readers read them
 * together. aria-invalid marks the field as having an error.
 */
export function TextField({ id, label, hint, error, className = '', ...inputProps }) {
  const describedBy = error ? `${id}-error` : hint ? `${id}-hint` : undefined;
  return (
    <div className={`flex flex-col gap-1.5 ${className}`}>
      <label htmlFor={id} className="text-sm font-medium text-ink">
        {label}
      </label>
      <input
        id={id}
        aria-invalid={error ? true : undefined}
        aria-describedby={describedBy}
        className={`h-10 rounded-md border bg-surface px-3 text-sm text-ink placeholder:text-muted ${
          error ? 'border-crit' : 'border-rule'
        }`}
        {...inputProps}
      />
      {error ? (
        <p id={`${id}-error`} className="text-sm text-crit">
          {error}
        </p>
      ) : (
        hint && (
          <p id={`${id}-hint`} className="text-sm text-muted">
            {hint}
          </p>
        )
      )}
    </div>
  );
}
