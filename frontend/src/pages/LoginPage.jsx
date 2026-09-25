import { useState } from 'react';
import { Link } from 'react-router';
import { useAuth } from '../hooks/useAuth';
import { USE_MOCK_API } from '../utils/constants';
import { AuthLayout } from '../components/layout/AuthLayout';
import { Alert } from '../components/ui/Alert';
import { Button } from '../components/ui/Button';
import { TextField } from '../components/ui/TextField';

/**
 * Sign-in form. Each input is *controlled*: its value lives in React state and
 * every keystroke calls a setter, so the component always knows the current
 * values. After a successful sign-in, <PublicOnlyRoute> redirects automatically.
 */
export function LoginPage() {
  const { signIn, notice } = useAuth();
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState(null);
  const [submitting, setSubmitting] = useState(false);

  async function handleSubmit(event) {
    event.preventDefault(); // stop the browser's default full-page form submit
    setError(null);
    setSubmitting(true);
    try {
      await signIn(email.trim(), password);
      // No navigate() here: PublicOnlyRoute sees the new status and redirects.
    } catch (err) {
      setError(err);
      setSubmitting(false);
    }
  }

  return (
    <AuthLayout
      title="Sign in"
      subtitle="Retail analytics and forecasting for your sales data."
      footer={
        <>
          No account yet?{' '}
          <Link to="/register" className="font-medium text-accent underline-offset-2 hover:underline">
            Create one
          </Link>
        </>
      }
    >
      <form onSubmit={handleSubmit} noValidate className="flex flex-col gap-4">
        {notice && <Alert tone="warning">{notice}</Alert>}
        {error && <Alert tone="error">{error.message}</Alert>}
        <TextField
          id="login-email"
          label="Email"
          type="email"
          autoComplete="email"
          value={email}
          onChange={(event) => setEmail(event.target.value)}
          required
        />
        <TextField
          id="login-password"
          label="Password"
          type="password"
          autoComplete="current-password"
          value={password}
          onChange={(event) => setPassword(event.target.value)}
          required
        />
        <Button type="submit" loading={submitting} disabled={!email || !password}>
          Sign in
        </Button>
        {USE_MOCK_API && (
          <p className="text-xs text-muted">
            Mock mode: create any account. It is stored only in this browser.
          </p>
        )}
      </form>
    </AuthLayout>
  );
}
