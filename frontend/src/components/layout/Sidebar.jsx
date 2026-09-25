import { NavLink } from 'react-router';
import { Brand } from './Brand';
import { useDatasets } from '../../hooks/useDatasets';
import { PLANNED_PAGES } from '../../content/plannedPages';
import { DATASET_STATUS } from '../../utils/constants';
import { Badge } from '../ui/Badge';

const linkClasses = ({ isActive }) =>
  `flex items-center justify-between gap-2 rounded-md px-3 py-2 text-sm ${
    isActive ? 'bg-accent-soft font-semibold text-accent' : 'text-ink-2 hover:bg-surface-2 hover:text-ink'
  }`;

function NavSection({ title, children }) {
  return (
    <div>
      <p className="px-3 pb-1 text-[11px] font-medium tracking-wider text-muted uppercase">{title}</p>
      <ul className="flex flex-col gap-0.5">{children}</ul>
    </div>
  );
}

/**
 * Main navigation. The "Current dataset" section only appears when a dataset
 * is open, and pages the dataset can't support are shown disabled with the
 * reason (architecture §12.1 "capabilities").
 */
export function Sidebar({ onNavigate }) {
  const { currentDataset } = useDatasets();
  const capabilities = new Map((currentDataset?.capabilities ?? []).map((c) => [c.key, c]));
  const isReady = currentDataset?.status === DATASET_STATUS.READY;

  return (
    <nav aria-label="Main" className="flex h-full flex-col gap-6 overflow-y-auto px-3 py-5">
      <Brand className="px-3" />

      <NavSection title="Workspace">
        <li>
          <NavLink to="/datasets" end className={linkClasses} onClick={onNavigate}>
            Datasets
          </NavLink>
        </li>
        <li>
          <NavLink to="/upload" className={linkClasses} onClick={onNavigate}>
            Upload data
          </NavLink>
        </li>
      </NavSection>

      {currentDataset && (
        <NavSection title="Current dataset">
          <li className="truncate px-3 pb-1 text-xs text-muted" title={currentDataset.name}>
            {currentDataset.name}
          </li>
          <li>
            <NavLink to={`/datasets/${currentDataset.id}/quality`} className={linkClasses} onClick={onNavigate}>
              Data quality
            </NavLink>
          </li>
          {PLANNED_PAGES.map((page) => {
            const capability = capabilities.get(page.capability);
            const unavailable = isReady && capability && !capability.enabled;
            if (unavailable) {
              return (
                <li key={page.path}>
                  <span
                    className="flex cursor-not-allowed items-center justify-between gap-2 rounded-md px-3 py-2 text-sm text-muted"
                    title={`Unavailable for this dataset. Map: ${capability.missing.join(', ')}`}
                  >
                    {page.label}
                    <Badge>n/a</Badge>
                  </span>
                </li>
              );
            }
            return (
              <li key={page.path}>
                <NavLink
                  to={`/datasets/${currentDataset.id}/${page.path}`}
                  className={linkClasses}
                  onClick={onNavigate}
                >
                  {page.label}
                  <span className="font-mono text-[10px] text-muted">{page.phase.replace('Phase ', 'P')}</span>
                </NavLink>
              </li>
            );
          })}
        </NavSection>
      )}
    </nav>
  );
}
