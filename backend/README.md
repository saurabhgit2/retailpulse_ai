# RetailPulse AI — backend

FastAPI service for RetailPulse AI: accounts, CSV upload, column mapping, the cleaning pipeline
and the data-quality report (architecture Phases 2–3). Analytics, forecasting, segmentation,
association rules and the AI layer arrive in later phases.

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

## Sample data

```powershell
python scripts/generate_synthetic_data.py --rows 40000
```

Writes `data/sample/SYNTHETIC_retail_sales.csv`: invented data with deliberate problems
(duplicates, cancellations, missing customer IDs, zero prices, fee lines, unreadable dates). Tick
**"This dataset is synthetic"** when uploading it, and never report its numbers as findings.

For the real dataset, download Online Retail II from Kaggle and upload the CSV as-is.

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
│   ├── services/            use cases: upload, start processing, background job
│   └── preprocessing/       PURE pandas: field guide, dates, detection, validation, cleaning
├── alembic/versions/        one migration per schema change
├── scripts/                 synthetic data generator
└── tests/                   unit (pure) · api · integration
```

The rule that keeps this maintainable: **`app/preprocessing/` imports no web framework and no
ORM.** It takes DataFrames and returns plain data, so it can be tested in milliseconds and reused
by the research scripts in Phase 5.

## Common problems

| Symptom | Cause and fix |
|---|---|
| `JWT_SECRET_KEY is not set` | Generate one and put it in `.env` (step 3 above). |
| `connection refused` on port 5432 | The database container isn't running: `docker compose up -d db`. |
| `alembic: command not found` | The virtual environment isn't active. Activate it, then reinstall. |
| Tests say "Test database is not reachable" | Create it: `docker compose exec db createdb -U retailpulse retailpulse_test`. |
| Upload returns 413 | The file is over `MAX_UPLOAD_MB` in `.env` (default 200). |
