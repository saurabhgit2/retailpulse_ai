import { buttonClasses } from './buttonStyles';
import { Spinner } from './Spinner';

/**
 * A button with consistent styles and a loading state.
 * `...rest` passes any other prop (onClick, aria-label, form…) straight to the
 * underlying <button>, so this component never gets in the way.
 */
export function Button({
  variant = 'primary',
  size = 'md',
  loading = false,
  disabled = false,
  type = 'button', // default to "button" so it never submits a form by accident
  className = '',
  children,
  ...rest
}) {
  return (
    <button
      type={type}
      disabled={disabled || loading}
      aria-busy={loading || undefined}
      className={buttonClasses({ variant, size, className })}
      {...rest}
    >
      {loading && <Spinner size="sm" label="Working" />}
      {children}
    </button>
  );
}
