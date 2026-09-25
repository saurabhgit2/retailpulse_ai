import { describe, expect, it, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router';
import { AuthContext } from '../context/auth-context';
import { ApiError } from '../services/apiClient';
import { LoginPage } from './LoginPage';

// Render the page with a fake auth context: the test controls what signIn does,
// so no server (real or mock) is involved.
function renderLogin(auth) {
  const value = { status: 'anonymous', notice: null, user: null, signOut: vi.fn(), register: vi.fn(), ...auth };
  return render(
    <MemoryRouter>
      <AuthContext.Provider value={value}>
        <LoginPage />
      </AuthContext.Provider>
    </MemoryRouter>,
  );
}

describe('LoginPage', () => {
  it('sends the trimmed email and the password to signIn', async () => {
    const signIn = vi.fn().mockResolvedValue(undefined);
    renderLogin({ signIn });

    await userEvent.type(screen.getByLabelText('Email'), '  me@example.com ');
    await userEvent.type(screen.getByLabelText('Password'), 'correct horse battery');
    await userEvent.click(screen.getByRole('button', { name: 'Sign in' }));

    expect(signIn).toHaveBeenCalledWith('me@example.com', 'correct horse battery');
  });

  it("shows the server's message when sign-in fails", async () => {
    const signIn = vi.fn().mockRejectedValue(
      new ApiError({ status: 401, code: 'INVALID_CREDENTIALS', message: 'Email or password is incorrect.' }),
    );
    renderLogin({ signIn });

    await userEvent.type(screen.getByLabelText('Email'), 'me@example.com');
    await userEvent.type(screen.getByLabelText('Password'), 'wrong password!!');
    await userEvent.click(screen.getByRole('button', { name: 'Sign in' }));

    expect(await screen.findByRole('alert')).toHaveTextContent('Email or password is incorrect.');
  });

  it('shows why the user was signed out', () => {
    renderLogin({ signIn: vi.fn(), notice: 'Your session has expired. Sign in again.' });
    expect(screen.getByText('Your session has expired. Sign in again.')).toBeInTheDocument();
  });
});
