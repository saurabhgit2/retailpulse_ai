# RetailPulse AI — backend

FastAPI service for RetailPulse AI: accounts, file upload (CSV **and** Excel), column mapping, the
cleaning pipeline, the data-quality report, and the analytics and entropy layer (architecture
Phases 2–4). Forecasting, segmentation, association rules and the AI layer arrive in later phases.

The architecture is in `docs/ARCHITECTURE.md`. A walkthrough written for learning is in
`docs/BACKEND_GUIDE.md`.

## Requirements

- **Python 3.11 or newer** (`python --version`)
- **Docker Desktop** for PostgreSQL 16 (`docker --version`)

## Setup (Windows PowerShell)

```powershell
# 1. Database (from the repository root, where docker-compose.yml is)
docker compose up -d db
docker compose exec db createdb -U retailpulse retailpulse_test   # for the tests

# 2. Python environment
cd backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements-dev.txt

# 3. Configuration
Copy-Item .env.example .env
python -c "import secrets; print(secrets.token_urlsafe(48))"      # paste into JWT_SECRET_KEY

# 4. Create the tables
alembic upgrade head

# 5. Run it
uvicorn app.main:app --reload
```

On macOS or Linux, use `source .venv/bin/activate` and `cp .env.example .env`.

- API: http://localhost:8000/api/v1
- Interactive docs: http://localhost:8000/docs
- Health check: http://localhost:8000/api/v1/health

## Connecting the frontend

In `frontend/.env`, set `VITE_USE_MOCK_API=false`, then restart `npm run dev`. The Vite dev server
forwards `/api` to `http://localhost:8000`, so the browser sees one origin and CORS never comes up
locally.

## Scripts

```powershell
python scripts/generate_synthetic_data.py --rows 40000     # labelled synthetic test data
python scripts/profile_dataset.py ../data/raw/online_retail_II.xlsx   # EDA report
python scripts/excel_to_csv.py ../data/raw/online_retail_II.xlsx      # optional: faster re-runs
```

`profile_dataset.py` writes `PROFILE.md` plus CSVs: shape and exclusions, KPIs, distributions,
seasonality, concentration, entropy per feature and the series forecastability profile. Add
`--synthetic` when profiling invented data, and every figure is labelled as such.

Writes `data/sample/SYNTHETIC_retail_sales.csv`: invented data with deliberate problems
(duplicates, cancellations, missing customer IDs, zero prices, fee lines, unreadable dates). Tick
**"This dataset is synthetic"** when uploading it, and never report its numbers as findings.

For the real dataset, download Online Retail II from Kaggle and upload the `.xlsx` as-is: both
year-sheets are read and stacked. openpyxl is slow on a million rows, so if you will re-process it
more than once, convert it first with `scripts/excel_to_csv.py`.

## Tests

```powershell
pytest                    # everything
pytest tests/unit         # pure pipeline tests: no database needed
pytest -m db              # only the tests that use PostgreSQL
```

Tests that need the database are skipped with a message if `TEST_DATABASE_URL` is unreachable, so
`pytest` always runs.

## Layout

```
backend/
├── app/
│   ├── main.py              app factory: middleware, routers, error handlers
│   ├── core/                config, logging, error types, password hashing and JWT
│   ├── api/                 routes (HTTP only), dependencies, exception handlers
│   ├── schemas/             Pydantic request and response models
│   ├── db/                  engine, session, ORM models, repositories (SQL lives here)
│   ├── services/            use cases: upload, processing, analytics with caching
│   ├── preprocessing/       PURE pandas: field guide, dates, detection, validation, cleaning
│   └── analytics/           PURE pandas: KPIs, trends, entropy, statistics, anomalies
├── alembic/versions/        one migration per schema change
├── scripts/                 synthetic data generator
└── tests/                   unit (pure) · api · integration
```

The rule that keeps this maintainable: **`app/preprocessing/` and `app/analytics/` import no web
framework and no ORM.** They take DataFrames and return plain data, so they can be tested in
milliseconds — and reused directly by the research scripts, which is why the report and the
dashboard cannot disagree.

## Common problems

| Symptom | Cause and fix |
|---|---|
| `JWT_SECRET_KEY is not set` | Generate one and put it in `.env` (step 3 above). |
| `ECONNREFUSED` in the Vite terminal | The backend isn't running. It is a second program: `uvicorn app.main:app --reload` in its own terminal. |
| `connection refused` on port 5432 | The database container isn't running: `docker compose up -d db`. |
| `password authentication failed for user "retailpulse"` | Something else already owns port 5432 — usually a PostgreSQL installed natively (`Get-Service *postgres*`). Publish the container on another port: `'5433:5432'` in `docker-compose.yml`, and change the port in both URLs in `.env`. Check with `docker compose ps`. |
| `No 'script_location' key found in configuration` | You are not in `backend/`. Every project command runs from there, never from inside `.venv/`. |
| `alembic: command not found` | The virtual environment isn't active. Activate it, then reinstall. |
| Tests say "Test database is not reachable" | Create it: `docker compose exec db createdb -U retailpulse retailpulse_test`. |
| Upload returns 413 | The file is over `MAX_UPLOAD_MB` in `.env` (default 200). |
| An `.xlsx` upload takes minutes | openpyxl is slow at this scale. Convert once with `scripts/excel_to_csv.py` and upload the CSV. |
| An analytics endpoint returns 409 `CAPABILITY_UNAVAILABLE` | The dataset has no column for that analysis (Online Retail II has no category column). |
| Analytics return stale numbers after reprocessing | They should not: the cache is cleared on reprocess. If you see it, say so — that is a bug. |

Three things run at once: the database (Docker), the backend (`uvicorn`, port 8000) and the
frontend (`npm run dev`, port 5173). A server that has started looks idle — `Application startup
complete.` and then nothing is what success looks like. Open another terminal rather than
interrupting it.
