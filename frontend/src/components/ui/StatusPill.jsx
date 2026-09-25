import { DATASET_STATUS } from '../../utils/constants';

// Status is shown with a label and a colour, never colour alone.
const STATUS_STYLES = {
  [DATASET_STATUS.AWAITING_MAPPING]: { label: 'Needs mapping', className: 'bg-warn-soft text-warn' },
  [DATASET_STATUS.PROCESSING]: { label: 'Processing', className: 'bg-info-soft text-info' },
  [DATASET_STATUS.READY]: { label: 'Ready', className: 'bg-ok-soft text-ok' },
  [DATASET_STATUS.FAILED]: { label: 'Failed', className: 'bg-crit-soft text-crit' },
};

export function StatusPill({ status }) {
  const style = STATUS_STYLES[status] ?? { label: status, className: 'bg-surface-2 text-ink-2' };
  return (
    <span className={`inline-flex items-center gap-1.5 rounded-full px-2.5 py-0.5 text-xs font-semibold ${style.className}`}>
      <span className="h-1.5 w-1.5 rounded-full bg-current" aria-hidden="true" />
      {style.label}
    </span>
  );
}
