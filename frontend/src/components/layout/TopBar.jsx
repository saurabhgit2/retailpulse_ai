import { useAuth } from '../../hooks/useAuth';
import { Button } from '../ui/Button';
import { DatasetSwitcher } from './DatasetSwitcher';

export function TopBar({ onOpenMenu }) {
  const { user, signOut } = useAuth();
  return (
    <header className="flex h-14 items-center justify-between gap-3 border-b border-rule bg-surface px-4 sm:px-8">
      <div className="flex min-w-0 items-center gap-3">
        <Button variant="ghost" size="sm" className="lg:hidden" onClick={onOpenMenu} aria-label="Open navigation">
          Menu
        </Button>
        <DatasetSwitcher />
      </div>
      <div className="flex items-center gap-3">
        <span className="hidden truncate text-sm text-ink-2 sm:block" title={user?.email}>
          {user?.full_name || user?.email}
        </span>
        <Button variant="secondary" size="sm" onClick={() => signOut()}>
          Sign out
        </Button>
      </div>
    </header>
  );
}
