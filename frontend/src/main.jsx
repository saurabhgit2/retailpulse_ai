import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import { BrowserRouter } from 'react-router';
import { App } from './App';
import './index.css';

/*
 * The entry point Vite loads from index.html.
 * - createRoot attaches React to <div id="root">.
 * - StrictMode runs extra checks in development (it deliberately mounts
 *   components twice to expose effects that don't clean up after themselves).
 * - BrowserRouter keeps the UI in sync with the address bar.
 */
createRoot(document.getElementById('root')).render(
  <StrictMode>
    <BrowserRouter>
      <App />
    </BrowserRouter>
  </StrictMode>,
);
