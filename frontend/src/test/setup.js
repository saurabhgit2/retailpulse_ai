// Runs before every test file (configured in vite.config.js → test.setupFiles).
import '@testing-library/jest-dom/vitest'; // adds matchers like toBeInTheDocument()
import { cleanup } from '@testing-library/react';
import { afterEach } from 'vitest';

// Unmount whatever a test rendered, so tests can't affect each other.
afterEach(() => {
  cleanup();
});
