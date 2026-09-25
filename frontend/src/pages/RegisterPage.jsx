import { useState } from 'react';
import { Link } from 'react-router';
import { useAuth } from '../hooks/useAuth';
import { MIN_PASSWORD_LENGTH } from '../utils/constants';
import { validateRegistration } from '../utils/validation';
import { AuthLayout } from '../components/layout/AuthLayout';
import { Alert } from '../components/ui/Alert';
import { Button } from '../components/ui/Button';
import { TextField } from '../components/ui/TextField';

export function RegisterPage() {
  const { register } = useAuth();
  // One state object for the whole form; each field updates its own key.
  const [values, setValues] = useState({ fullName: '', email: '', password: '', confirmPassword: '' });
  const [fieldErrors, setFieldErrors] = useState({});
  const [error, setError] = useState(null);
  const [submitting, setSubmitting] = useState(false);

  const update = (field) => (event) => setValues((previous) => ({ ...previous, [field]: event.target.value }));

  async function handleSubmit(event) {
    event.preventDefault();
    const errors = validateRegistration(values);
    setFieldErrors(errors);
    if (Object.keys(errors).length > 0) return; // show messages, don't call the server

    setError(null);
    setSubmitting(true);
    try {
      await register({ fullName: values.fullName.trim(), email: values.email.trim(), password: values.password });
    } catch (err) {
      setError(err);
      setSubmitting(false);
    }
  }

  return (
    <AuthLayout
      title="Create your account"
      footer={
        <>
          Already registered?{' '}
          <Link to="/login" className="font-medium text-accent underline-offset-2 hover:underline">
            Sign in
          </Link>
        </>
      }
    >
      <form onSubmit={handleSubmit} noValidate className="flex flex-col gap-4">
        {error && <Alert tone="error">{error.message}</Alert>}
        <TextField id="register-name" label="Full name" autoComplete="name" value={values.fullName} onChange={update('fullName')} error={fieldErrors.fullName} />
        <TextField id="register-email" label="Email" type="email" autoComplete="email" value={values.email} onChange={update('email')} error={fieldErrors.email} />
        <TextField
          id="register-password"
          label="Password"
          type="password"
          autoComplete="new-password"
          hint={`At least ${MIN_PASSWORD_LENGTH} characters. A short sentence works well.`}
          value={values.password}
          onChange={update('password')}
          error={fieldErrors.password}
        />
        <TextField
          id="register-confirm"
          label="Confirm password"
          type="password"
          autoComplete="new-password"
          value={values.confirmPassword}
          onChange={update('confirmPassword')}
          error={fieldErrors.confirmPassword}
        />
        <Button type="submit" loading={submitting}>
          Create account
        </Button>
      </form>
    </AuthLayout>
  );
}
