import { Link } from 'react-router';
import { buttonClasses } from '../components/ui/buttonStyles';
import { EmptyState } from '../components/ui/EmptyState';

export function NotFoundPage() {
  return (
    <EmptyState
      title="Page not found"
      action={
        <Link to="/datasets" className={buttonClasses({ variant: 'secondary' })}>
          Go to datasets
        </Link>
      }
    >
      The address may be mistyped, or the page may not exist yet.
    </EmptyState>
  );
}
