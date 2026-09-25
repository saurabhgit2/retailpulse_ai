import { describe, expect, it } from 'vitest';
import { validateRegistration } from './validation';

const valid = { fullName: 'Saurabh', email: 'saurabh@example.com', password: 'a long enough pass', confirmPassword: 'a long enough pass' };

describe('validateRegistration', () => {
  it('returns no errors for valid input', () => {
    expect(validateRegistration(valid)).toEqual({});
  });

  it('requires the minimum password length', () => {
    const errors = validateRegistration({ ...valid, password: 'short', confirmPassword: 'short' });
    expect(errors.password).toMatch(/at least 12/);
  });

  it('catches mismatched confirmation and bad email', () => {
    const errors = validateRegistration({ ...valid, email: 'nope', confirmPassword: 'different value' });
    expect(Object.keys(errors).sort()).toEqual(['confirmPassword', 'email']);
  });
});
