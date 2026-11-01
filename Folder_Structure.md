# Repository structure

**As built, November 2026.** An earlier version of this file described the structure
proposed in Phase 1; this one describes what exists. Where the two differ, the
difference is a recorded scope decision rather than unfinished work — the notable ones
are listed at the foot.

```
retailpulse_ai/
├── README.md                     # Project overview, quick start, scope
├── Folder_Structure.md           # This file
├── docker-compose.yml            # PostgreSQL 16 — the only container
├── pytest.ini
├── .gitignore                    # .env, data/raw, data/uploads, node_modules, .venv
├── rq2_run_k3.log                # Console captures, kept for the record. The
├── rq3_run_capped200.log         #   authoritative output of a run is always its
├── rq3_run_uncapped.log          #   directory under research/results/
├── rq4_run.log
│
├── backend/                      # FastAPI service — about 160 Python modules
│   ├── README.md
│   ├── .env.example              # DATABASE_URL, JWT_SECRET_KEY, … placeholders only
│   ├── requirements.txt · requirements-dev.txt
│   ├── alembic.ini · alembic/versions/      # one migration per schema change
│   ├── scripts/
│   │   ├── generate_synthetic_data.py       # labelled SYNTHETIC data for development
│   │   ├── profile_dataset.py               # EDA report over a raw file
│   │   ├── excel_to_csv.py                  # one-off conversion; openpyxl is slow
│   │   ├── reconcile_invoices.py            # every invoice, raw file to stored dataset
│   │   └── measure_latency.py               # warm API latency against the 3s target
│   ├── artifacts/performance/               # latency measurement runs + their README
│   ├── app/
│   │   ├── main.py               # app factory: middleware, routers, error handlers
│   │   ├── core/                 # config, logging, error types, hashing, JWT
│   │   ├── api/                  # routes (HTTP only), dependencies, exception handlers
│   │   ├── schemas/              # Pydantic request and response models
│   │   ├── db/                   # engine, session, ORM models, repositories (SQL lives here)
│   │   ├── services/             # use cases: upload, processing, analytics with caching
│   │   ├── utils/                # dates (ISO weeks, partial periods), hashing
│   │   │
│   │   │   ── the pure core: no web framework, no ORM, no database session ──
│   │   ├── preprocessing/        # field guide, dates, detection, validation, 12-step cleaning
│   │   ├── analytics/            # kpis, trends, breakdowns, distributions, seasonality,
│   │   │                         #   relationships, statistics, features, entropy, rfm,
│   │   │                         #   series_profile, anomalies
│   │   ├── forecasting/          # splits, metrics, baselines, statistical, ml, combination,
│   │   │                         #   intervals, significance, registry
│   │   ├── segmentation/         # rfm windows, clustering, quality, stability
│   │   ├── association/          # baskets, mining, actionability
│   │   └── insights/             # reconciliation across engines; both RQ4 conditions
│   └── tests/                    # 637 tests — unit (pure) · api · integration
│
├── frontend/                     # React SPA — about 140 modules, 280 tests
│   ├── README.md
│   ├── .env.example              # VITE_ variables only; public by definition
│   ├── package.json · vite.config.js · index.html
│   └── src/
│       ├── main.jsx · App.jsx · routes.jsx · index.css
│       ├── pages/                # Login, Register, Datasets, UploadWizard, DataQuality,
│       │                         #   Dashboard, Explore, Forecasting, Customers, Baskets,
│       │                         #   Statistics, Insights, NotFound
│       ├── components/
│       │   ├── layout/           # AppShell, Sidebar, TopBar, DatasetSwitcher, FilterBar
│       │   ├── ui/               # Button, Card, Alert, Badge, KpiCard, Spinner, StatusPill
│       │   ├── upload/           # FileDropzone, ColumnMappingTable, QualityReport
│       │   ├── explain/          # MethodCard
│       │   ├── auth/             # ProtectedRoute, PublicOnlyRoute
│       │   ├── shared/           # histogramShape, provenance — reused by several pages
│       │   └── dashboard/ forecasting/ customers/ baskets/ explore/ statistics/
│       │                         #   one pure adapter per page, each with a fixture
│       │                         #   captured from the real endpoint, and its tests
│       ├── charts/               # hand-written SVG: scale, path, axisFormat, series,
│       │                         #   tokens.css, ChartFrame, ChartTable, Legend,
│       │                         #   LineChart, BarChart, ColumnChart, SlopeChart
│       ├── services/             # apiClient + one module per resource (+ mock/)
│       ├── hooks/                # useApi, usePolling, useAuth, useDatasets, useFilters
│       ├── context/              # AuthProvider, DatasetProvider
│       ├── content/              # plannedPages.js — now empty; every page is built
│       └── utils/                # format, csv, dates, capabilities, validation
│
├── research/                     # EXPERIMENTS — separate programs, same core code
│   ├── README.md                 # How to reproduce each result
│   ├── configs/                  # rq1_forecasting · rq2_segmentation ·
│   │                             #   rq3_association · rq4_insights  (TOML, pre-declared)
│   ├── run_experiment.py         # RQ1
│   ├── run_segmentation.py       # RQ2
│   ├── run_association.py        # RQ3
│   ├── run_insights.py           # RQ4
│   └── results/                  # one timestamped directory per run: config.toml,
│                                 #   run.json (config hash, environment, protocol,
│                                 #   per-fold results, significance), CSV tables
│
├── data/
│   ├── sample/                   # SYNTHETIC_retail_sales.csv + README stating it is synthetic
│   ├── raw/                      # online_retail_II.xlsx — git-ignored
│   └── uploads/                  # stored uploads — git-ignored
│
└── docs/
    ├── ARCHITECTURE.md           # Phase 1 design document
    ├── BACKEND_GUIDE.md          # walkthrough of backend/
    ├── FRONTEND_GUIDE.md         # walkthrough of frontend/
    └── RUNNING_LOCALLY.md        # setup, daily start-up, and what goes wrong
```

## Where this differs from the Phase 1 plan

| Planned | Built | Why |
|---|---|---|
| `app/ai/` — providers, prompts, grounding, chat | not built | A conversational assistant was withdrawn in Assessment 2: it supported no research question. No generative model is used anywhere in the project. |
| `app/recommendations/` | `app/insights/` | The reconciliation layer exists under a different name and runs as a research pipeline rather than behind an API. |
| Routes for segmentations, associations, recommendations, ai | not built | Assessment 2 scopes the dashboard to the analyses the API exposes; these engines are reported as research output, with the limitation recorded. |
| `charts/` using Recharts | hand-written SVG | Every other analytical component is implemented from its definition so the dissertation can explain it; the chart layer follows the same rule. |
| `forecasting/deep.py` — LSTM | not built | Assessment 1 §9.5 permitted dropping it. The comparison stands on statistical, tree-based and combination approaches. |
| `.github/workflows/ci.yml` | not built | Continuous integration was third on the declared cut line. 917 tests run locally. |
| `docs/adr/`, `API.md`, `DATABASE.md`, `MODELS.md`, `AI.md`, `TESTING.md` | not built | The architecture document covers the contract and the data model; the guides cover the rest. |
| `research/notebooks/`, `research/notes/` | not built | Results are recorded in run directories rather than notebooks, which keeps them re-executable. |
| `data/artifacts/` | not used | No model files are persisted; forecast runs are stored in the database. |
