# RetailPulse AI — frontend

React single-page application: sign-in, dataset upload with column mapping, background
processing, the data-quality report, and seven analysis pages.

The architecture is in [`../docs/ARCHITECTURE.md`](../docs/ARCHITECTURE.md). A
walkthrough of this folder, written so it can be rebuilt from, is in
[`../docs/FRONTEND_GUIDE.md`](../docs/FRONTEND_GUIDE.md). Setup and daily operation are
in [`../docs/RUNNING_LOCALLY.md`](../docs/RUNNING_LOCALLY.md).

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

Open <http://localhost:5173>, create an account, then **Upload data → Use a synthetic
sample file** to try the whole flow without a backend.

### Mock mode vs the real backend

| `VITE_USE_MOCK_API` | What happens |
|---|---|
| `true` (default) | An in-browser mock (`src/services/mock/`) answers every API call. No backend needed. Accounts and dataset metadata live in this browser's localStorage. Reports are computed from the first ~5,000 rows of your file and are labelled **Mock**. |
| `false` | Requests go to `/api/v1/...`. The Vite dev server forwards them to `DEV_API_TARGET` (default `http://localhost:8000`), where FastAPI runs. |

Nothing else in the app changes between the two modes: the mock returns real `Response`
objects with the same status codes and error envelope as the backend contract
(architecture §9).

The analysis pages need the real backend — the mock covers upload and quality, not the
analytics endpoints.

To clear the mock's data, run `localStorage.removeItem('retailpulse.mock.v1')` in the
browser console.

## Pages

| Route | Page |
|---|---|
| `/datasets` | Dataset list and switcher |
| `/upload` | Upload wizard: drop, detect, map, process |
| `/datasets/:id/quality` | What the cleaning pipeline did, and what it withheld |
| `/datasets/:id/dashboard` | Headline figures with URL-synced date and region filters |
| `/datasets/:id/explore` | Calendar seasonality, weekly trend, revenue-per-line distribution |
| `/datasets/:id/forecasting` | Start a run, poll it, compare models on a locked hold-out |
| `/datasets/:id/customers` | RFM segments, concentration, value and recency distributions |
| `/datasets/:id/baskets` | Basket size and order value, linear or logarithmic |
| `/datasets/:id/statistics` | Descriptive statistics, group comparison, mutual information, series profile |
| `/datasets/:id/insights` | Where the insight layer lives, and why it is not a page here |

Each analysis page follows the same shape: a **pure adapter** under
`components/<page>/`, tested against a fixture captured from the real endpoint, and a
page component that only arranges what the adapter returns. Those fixtures are the only
place this application knows the server's field names, so a change to the API contract
fails a test rather than a screen.

## Scripts

| Command | Does |
|---|---|
| `npm run dev` | Development server with hot reload |
| `npm run build` | Production build into `dist/` |
| `npm run preview` | Serve the production build locally |
| `npm test` | Vitest in watch mode |
| `npm run test:run` | Run all tests once — **280 across 26 files** |
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
│   ├── layout/         AppShell, Sidebar, TopBar, DatasetSwitcher, FilterBar…
│   ├── ui/             Button, Card, Alert, Badge, KpiCard, Spinner, StatusPill…
│   ├── upload/         wizard steps, mapping table, quality report
│   ├── explain/        MethodCard ("About this analysis")
│   ├── auth/           ProtectedRoute, PublicOnlyRoute
│   ├── shared/         histogramShape, provenance — adapters several pages reuse
│   └── dashboard/ forecasting/ customers/ baskets/ explore/ statistics/
│                       one pure adapter module per page, with its fixture and tests
├── charts/             hand-written SVG chart layer — see charts/README.md
├── services/           the only code that talks HTTP (+ mock/ for mock mode)
├── hooks/              useApi, usePolling, useAuth, useDatasets, useFilters
├── context/            AuthProvider, DatasetProvider
├── content/            explanation text; plannedPages.js (now empty — all pages built)
├── utils/              pure helpers: formatting, CSV, dates, capabilities, validation
└── test/setup.js       test environment setup
```

Tests sit next to the code they test (`*.test.js` / `*.test.jsx`).

**The charts are not Recharts or any other library** — they are hand-written SVG, for
the reasons in [`src/charts/README.md`](src/charts/README.md).

## Environment variables

Only variables prefixed `VITE_` reach the browser, and anyone can read them in the
bundled JavaScript. **Never put secrets in them.** See `.env.example` for the full list.
