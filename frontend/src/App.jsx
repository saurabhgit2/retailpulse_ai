import { AuthProvider } from './context/AuthProvider';
import { AppRoutes } from './routes';

/** The root component: app-wide providers, then the routes. */
export function App() {
  return (
    <AuthProvider>
      <AppRoutes />
    </AuthProvider>
  );
}
