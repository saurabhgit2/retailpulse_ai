import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { AuthContext } from './auth-context';
import { configureAuth } from '../services/apiClient';
import * as authService from '../services/auth';

/*
 * Holds "who is signed in" for the whole app.
 *
 * Token storage (architecture §16): the token lives in React state and is
 * mirrored to sessionStorage, so a page reload doesn't sign you out, while
 * closing the tab does. sessionStorage can still be read by injected scripts
 * (XSS), so we rely on React escaping all rendered text and on short token
 * lifetimes. An httpOnly cookie would be the stricter alternative.
 */
const TOKEN_KEY = 'retailpulse.token';

function readStoredToken() {
  try {
    return sessionStorage.getItem(TOKEN_KEY);
  } catch {
    return null; // storage can be blocked (e.g. some private-browsing modes)
  }
}

function writeStoredToken(token) {
  try {
    if (token) sessionStorage.setItem(TOKEN_KEY, token);
    else sessionStorage.removeItem(TOKEN_KEY);
  } catch {
    // Ignore: the session then simply won't survive a reload.
  }
}

export function AuthProvider({ children }) {
  const [token, setToken] = useState(readStoredToken);
  const [user, setUser] = useState(null);
  // 'checking' while we confirm a stored token with the server.
  const [status, setStatus] = useState(() => (readStoredToken() ? 'checking' : 'anonymous'));
  const [notice, setNotice] = useState(null); // e.g. "Your session has expired."

  // The API client reads the token through this ref, so it always sees the
  // latest value without being re-configured on every render.
  const tokenRef = useRef(token);

  const signOut = useCallback((reason = null) => {
    tokenRef.current = null;
    writeStoredToken(null);
    setToken(null);
    setUser(null);
    setStatus('anonymous');
    setNotice(reason);
  }, []);

  // Dependency injection: give the API client a way to read the token and to
  // report an expired session, without the client importing React.
  useEffect(() => {
    configureAuth({
      getToken: () => tokenRef.current,
      onUnauthorized: () => signOut('Your session has expired. Sign in again.'),
    });
  }, [signOut]);

  // On first load with a stored token, ask the server who it belongs to.
  useEffect(() => {
    if (status !== 'checking') return undefined;
    const controller = new AbortController();
    authService
      .getCurrentUser({ signal: controller.signal })
      .then((me) => {
        setUser(me);
        setStatus('authenticated');
      })
      .catch((error) => {
        if (error?.name === 'AbortError') return;
        signOut(error?.status === 401 ? 'Your session has expired. Sign in again.' : null);
      });
    return () => controller.abort();
  }, [status, signOut]);

  const signIn = useCallback(
    async (email, password) => {
      const { access_token: accessToken } = await authService.login(email, password);
      tokenRef.current = accessToken; // needed immediately by the next request
      try {
        const me = await authService.getCurrentUser();
        writeStoredToken(accessToken);
        setToken(accessToken);
        setUser(me);
        setStatus('authenticated');
        setNotice(null);
      } catch (error) {
        signOut();
        throw error;
      }
    },
    [signOut],
  );

  const register = useCallback(
    async ({ fullName, email, password }) => {
      await authService.register({ fullName, email, password });
      await signIn(email, password);
    },
    [signIn],
  );

  // useMemo keeps the context value stable, so components that use it only
  // re-render when something in it actually changes.
  const value = useMemo(
    () => ({ user, token, status, notice, signIn, signOut, register }),
    [user, token, status, notice, signIn, signOut, register],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}
