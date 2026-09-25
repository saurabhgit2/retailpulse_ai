/**
 * Form validation rules. Pure functions (input -> output, no side effects), so
 * they are trivial to unit-test and reuse. The server validates again: client
 * checks are for fast feedback only.
 */
import { MIN_PASSWORD_LENGTH } from './constants';

const EMAIL_PATTERN = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

/** @returns {Record<string, string>} one message per invalid field (empty if valid) */
export function validateRegistration({ fullName, email, password, confirmPassword }) {
  const errors = {};
  if (!fullName.trim()) errors.fullName = 'Enter your name.';
  if (!EMAIL_PATTERN.test(email.trim())) errors.email = 'Enter a valid email address.';
  if (password.length < MIN_PASSWORD_LENGTH) {
    errors.password = `Use at least ${MIN_PASSWORD_LENGTH} characters.`;
  }
  if (confirmPassword !== password) errors.confirmPassword = 'The passwords do not match.';
  return errors;
}
