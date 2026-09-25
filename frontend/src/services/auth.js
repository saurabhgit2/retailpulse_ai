/**
 * Authentication endpoints (architecture §9.2, "Platform and authentication").
 */
import { api } from './apiClient';

/**
 * FastAPI's OAuth2 password flow expects a *form* body with the fields
 * `username` and `password` (not JSON). We use the email as the username.
 * @returns {Promise<{ access_token: string, token_type: 'bearer' }>}
 */
export function login(email, password) {
  return api.postForm('/auth/login', { username: email, password });
}

/** @returns {Promise<{ id, email, full_name }>} */
export function register({ fullName, email, password }) {
  return api.post('/auth/register', { full_name: fullName, email, password });
}

export function getCurrentUser({ signal } = {}) {
  return api.get('/auth/me', { signal });
}
