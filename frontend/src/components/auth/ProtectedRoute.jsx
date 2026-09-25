import { Navigate, useLocation } from 'react-router';
import { useAuth } from '../../hooks/useAuth';
import { FullPageSpinner } from '../ui/Spinner';

/**
 * Wraps pages that need a signed-in user. Anyone else is sent to /login, and
 * the page they wanted is remembered in navigation state so they come back to
 * it after signing in.
 *
 * This only protects the *interface*. The real protection is the backend
 * rejecting requests without a valid token: never rely on the frontend alone.
 */
export function ProtectedRoute({ children }) {
  const { status } = useAuth();
  const location = useLocation();

  if (status === 'checking') return <FullPageSpinner label="Checking your session…" />;
  if (status !== 'authenticated') {
    return <Navigate to="/login" replace state={{ from: location.pathname + location.search }} />;
  }
  return children;
}
