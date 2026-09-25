import { defineConfig, loadEnv } from 'vite';
import react from '@vitejs/plugin-react';
import tailwindcss from '@tailwindcss/vite';

// https://vite.dev/config/
export default defineConfig(({ mode }) => {
  // loadEnv with prefix '' reads ALL variables from .env files, including ones
  // without the VITE_ prefix. DEV_API_TARGET is only used here, on your machine,
  // so it is never bundled into the code sent to the browser.
  const env = loadEnv(mode, process.cwd(), '');

  return {
    plugins: [react(), tailwindcss()],
    server: {
      port: 5173,
      // In development the browser talks to Vite (localhost:5173). Vite forwards
      // anything under /api to the FastAPI server, so the browser sees one origin
      // and no CORS configuration is needed locally.
      proxy: {
        '/api': {
          target: env.DEV_API_TARGET || 'http://localhost:8000',
          changeOrigin: true,
        },
      },
    },
    // Vitest reads this block. jsdom gives tests a simulated browser DOM.
    test: {
      environment: 'jsdom',
      setupFiles: './src/test/setup.js',
      css: false,
      restoreMocks: true,
    },
  };
});
