import { useContext } from 'react';
import { AuthContext } from '../context/auth-context';

/** Read the signed-in user and auth actions from anywhere below <AuthProvider>. */
export function useAuth() {
  const value = useContext(AuthContext);
  if (!value) throw new Error('useAuth must be used inside <AuthProvider>.');
  return value;
}
