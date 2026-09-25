/**
 * Class names for buttons, shared by <Button> and by links that should look
 * like buttons (e.g. "Upload dataset"). A link that navigates must stay an <a>
 * element for accessibility, even if it looks like a button.
 */
const BASE =
  'inline-flex items-center justify-center gap-2 rounded-md font-medium whitespace-nowrap transition-colors disabled:cursor-not-allowed disabled:opacity-50';

const VARIANTS = {
  primary: 'bg-accent text-accent-ink hover:brightness-110',
  secondary: 'border border-rule bg-surface text-ink hover:bg-surface-2',
  ghost: 'text-ink-2 hover:bg-surface-2 hover:text-ink',
  danger: 'border border-rule bg-surface text-crit hover:bg-crit-soft',
};

const SIZES = {
  sm: 'h-8 px-3 text-sm',
  md: 'h-10 px-4 text-sm',
};

export function buttonClasses({ variant = 'primary', size = 'md', className = '' } = {}) {
  return [BASE, VARIANTS[variant], SIZES[size], className].filter(Boolean).join(' ');
}
