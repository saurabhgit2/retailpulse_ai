import { Navigate, useLocation } from 'react-router';
import { useAuth } from '../../hooks/useAuth';
import { FullPageSpinner } from '../ui/Spinner';

/**
 * Wraps the sign-in and register pages. Once the user is signed in, it sends
 * them on to the page they originally asked for (or the datasets list). The
 * login form itself therefore never needs to navigate.
 */
export function PublicOnlyRoute({ children }) {
  const { status } = useAuth();
  const location = useLocation();

  if (status === 'checking') return <FullPageSpinner label="Checking your session…" />;
  if (status === 'authenticated') {
    return <Navigate to={location.state?.from ?? '/datasets'} replace />;
  }
  return children;
}
