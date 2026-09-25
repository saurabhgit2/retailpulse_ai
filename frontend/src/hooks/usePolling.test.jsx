import { describe, expect, it, vi } from 'vitest';
import { renderHook, waitFor } from '@testing-library/react';
import { usePolling } from './usePolling';

const wait = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
const isReady = (dataset) => dataset.status === 'ready';

describe('usePolling', () => {
  it('keeps polling until the job is finished, then stops', async () => {
    const responses = [{ status: 'processing' }, { status: 'processing' }, { status: 'ready' }];
    // Defined outside renderHook so it is the same function on every render,
    // like a useCallback-wrapped fetcher in a real component.
    const fetcher = vi.fn(async () => responses.shift() ?? { status: 'ready' });

    const { result } = renderHook(() => usePolling(fetcher, { isDone: isReady, intervalMs: 5 }));

    await waitFor(() => expect(result.current.data?.status).toBe('ready'));
    await wait(30);
    expect(fetcher).toHaveBeenCalledTimes(3); // no requests after "ready"
  });

  it('stops polling when the component unmounts', async () => {
    const fetcher = vi.fn(async () => ({ status: 'processing' }));
    const { unmount } = renderHook(() => usePolling(fetcher, { isDone: isReady, intervalMs: 5 }));

    await waitFor(() => expect(fetcher).toHaveBeenCalled());
    unmount();
    const callsAtUnmount = fetcher.mock.calls.length;
    await wait(30);
    expect(fetcher.mock.calls.length).toBe(callsAtUnmount);
  });

  it('stops and exposes the error when a request fails', async () => {
    const failure = new Error('server down');
    const fetcher = vi.fn(async () => {
      throw failure;
    });
    const { result } = renderHook(() => usePolling(fetcher, { isDone: isReady, intervalMs: 5 }));

    await waitFor(() => expect(result.current.error).toBe(failure));
    await wait(30);
    expect(fetcher).toHaveBeenCalledTimes(1);
  });
});
