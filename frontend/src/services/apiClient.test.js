import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { ApiError, api, configureAuth, setTransport } from './apiClient';

const json = (status, body) =>
  new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } });

describe('apiClient', () => {
  let transport;

  beforeEach(() => {
    transport = vi.fn();
    setTransport(transport);
    configureAuth({ getToken: () => null, onUnauthorized: () => {} });
  });

  afterEach(() => setTransport(null));

  it('prefixes the API base path and returns parsed JSON', async () => {
    transport.mockResolvedValue(json(200, { items: [] }));
    await expect(api.get('/datasets')).resolves.toEqual({ items: [] });
    expect(transport.mock.calls[0][0]).toBe('/api/v1/datasets');
  });

  it('repeats array query parameters and skips empty ones', async () => {
    transport.mockResolvedValue(json(200, {}));
    await api.get('/x', { query: { region: ['UK', 'France'], start: '', end: null } });
    expect(transport.mock.calls[0][0]).toBe('/api/v1/x?region=UK&region=France');
  });

  it('adds the bearer token when one is available', async () => {
    configureAuth({ getToken: () => 'abc123' });
    transport.mockResolvedValue(json(200, {}));
    await api.get('/auth/me');
    expect(transport.mock.calls[0][1].headers.Authorization).toBe('Bearer abc123');
  });

  it('turns the error envelope into an ApiError', async () => {
    transport.mockResolvedValue(
      json(422, { error: { code: 'MISSING_REQUIRED_FIELD', message: 'Map the date column.', request_id: 'r-1' } }),
    );
    const error = await api.post('/datasets/1/process', {}).catch((e) => e);
    expect(error).toBeInstanceOf(ApiError);
    expect(error).toMatchObject({ status: 422, code: 'MISSING_REQUIRED_FIELD', message: 'Map the date column.', requestId: 'r-1' });
  });

  it("understands FastAPI's default validation format", async () => {
    transport.mockResolvedValue(json(422, { detail: [{ loc: ['body', 'email'], msg: 'value is not a valid email' }] }));
    const error = await api.post('/auth/register', {}).catch((e) => e);
    expect(error.code).toBe('VALIDATION_ERROR');
    expect(error.message).toBe('email: value is not a valid email');
  });

  it('reports a network failure with a useful message', async () => {
    transport.mockRejectedValue(new TypeError('Failed to fetch'));
    const error = await api.get('/datasets').catch((e) => e);
    expect(error).toMatchObject({ status: 0, code: 'NETWORK_ERROR' });
  });

  it('lets cancelled requests through as AbortError, not as failures', async () => {
    transport.mockRejectedValue(new DOMException('Aborted', 'AbortError'));
    const error = await api.get('/datasets').catch((e) => e);
    expect(error.name).toBe('AbortError');
  });

  it('signals an expired session only when a token was sent', async () => {
    const onUnauthorized = vi.fn();
    transport.mockImplementation(async () => json(401, { error: { code: 'TOKEN_INVALID', message: 'Expired' } }));

    configureAuth({ getToken: () => null, onUnauthorized });
    await api.postForm('/auth/login', { username: 'a', password: 'b' }).catch(() => {});
    expect(onUnauthorized).not.toHaveBeenCalled(); // wrong password is not "session expired"

    configureAuth({ getToken: () => 'old-token', onUnauthorized });
    await api.get('/datasets').catch(() => {});
    expect(onUnauthorized).toHaveBeenCalledTimes(1);
  });

  it('returns null for 204 No Content', async () => {
    transport.mockResolvedValue(new Response(null, { status: 204 }));
    await expect(api.delete('/datasets/1')).resolves.toBeNull();
  });
});
