# RetailPulse AI — frontend

React single-page app for RetailPulse AI: sign-in, dataset upload with column mapping, background
processing, and the data-quality report. Analytics, forecasting and AI pages are placeholders that
arrive in later phases (see `src/content/plannedPages.js`).

The architecture is in `docs/ARCHITECTURE.md`. A walkthrough of every part of this folder, written
for learning, is in `docs/FRONTEND_GUIDE.md`.

## Requirements

- Node.js **20.19+ or 22.12+** (required by Vite 7). Check with `node --version`.
- npm (comes with Node).

## Run it

```bash
cd frontend
npm install              # downloads dependencies into node_modules/
cp .env.example .env     # Windows PowerShell: Copy-Item .env.example .env
npm run dev              # starts Vite on http://localhost:5173
```

Open http://localhost:5173, create an account, then choose **Upload data → Use a synthetic sample
file** to try the whole flow.

### Mock mode vs the real backend

| `VITE_USE_MOCK_API` | What happens |
|---|---|
| `true` (default) | An in-browser mock (`src/services/mock/`) answers every API call. No backend needed. Accounts and dataset metadata are kept in this browser's localStorage. Reports are computed from the first ~5,000 rows of your file and are labelled **Mock**. |
| `false` | Requests go to `/api/v1/...`. The Vite dev server forwards them to `DEV_API_TARGET` (default `http://localhost:8000`), where the FastAPI backend runs. |

Nothing else in the app changes between the two modes: the mock returns real `Response` objects
with the same status codes and error format as the backend contract (architecture §9).

To clear the mock's data, run `localStorage.removeItem('retailpulse.mock.v1')` in the browser
console, or clear the site data.

## Scripts

| Command | Does |
|---|---|
| `npm run dev` | Development server with hot reload |
| `npm run build` | Production build into `dist/` |
| `npm run preview` | Serve the production build locally |
| `npm test` | Vitest in watch mode |
| `npm run test:run` | Run all tests once (use this in CI) |
| `npm run lint` | ESLint |
| `npm run format` | Prettier |

## Folder map

```
src/
├── main.jsx            entry point: React root, StrictMode, router
├── App.jsx             app-wide providers + routes
├── routes.jsx          every URL and the page it shows
├── index.css           Tailwind import, colour tokens (light + dark)
├── pages/              one component per screen
├── components/
│   ├── layout/         AppShell, Sidebar, TopBar, DatasetSwitcher, AuthLayout, PageHeader…
│   ├── ui/             Button, Card, Alert, Badge, TextField, Spinner, StatusPill…
│   ├── upload/         the upload wizard steps, mapping table, quality report
│   ├── explain/        MethodCard ("About this analysis")
│   └── auth/           ProtectedRoute, PublicOnlyRoute
├── charts/             Recharts components (Phase 4)
├── services/           the only code that talks HTTP (+ mock/ for mock mode)
├── hooks/              useApi, usePolling, useAuth, useDatasets
├── context/            AuthProvider, DatasetProvider (+ context objects)
├── content/            explanation text and the list of planned pages
├── utils/              pure helpers: formatting, CSV, dates, capabilities, validation
└── test/setup.js       test environment setup
```

Tests sit next to the code they test (`*.test.js` / `*.test.jsx`).

## Environment variables

Only variables prefixed `VITE_` reach the browser, and anyone can read them in the bundled
JavaScript. **Never put secrets in them.** See `.env.example` for the full list.
