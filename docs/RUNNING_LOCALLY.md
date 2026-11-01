# Running RetailPulse AI locally

Three processes run at once: **PostgreSQL** in Docker, the **API** on port 8000, and the
**dev server** on port 5173. A server that has started looks idle —
`Application startup complete.` followed by nothing is what success looks like. Open
another terminal rather than interrupting it.

---

## First time

### 1. Database

From the repository root, where `docker-compose.yml` lives:

```powershell
docker compose up -d db
docker compose exec db createdb -U retailpulse retailpulse_test   # for the tests
docker compose ps                                                  # confirm it is healthy
```

If something already owns port 5432 — usually a natively installed PostgreSQL, which
`Get-Service *postgres*` will show — publish the container on another port by changing
`docker-compose.yml` to `'5433:5432'` and updating both URLs in `backend/.env`.

### 2. Backend

```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1          # macOS/Linux: source .venv/bin/activate
pip install -r requirements-dev.txt
Copy-Item .env.example .env           # macOS/Linux: cp .env.example .env
python -c "import secrets; print(secrets.token_urlsafe(48))"   # paste into JWT_SECRET_KEY
alembic upgrade head
uvicorn app.main:app --reload
```

- API: <http://localhost:8000/api/v1>
- Interactive docs: <http://localhost:8000/docs>
- Health: <http://localhost:8000/api/v1/health>

### 3. Frontend

In a second terminal:

```powershell
cd frontend
npm install
Copy-Item .env.example .env
npm run dev
```

Open <http://localhost:5173> and create an account. Vite forwards `/api` to port 8000, so
the browser sees one origin and CORS never arises locally.

### 4. Data

**Synthetic**, for trying the flow: *Upload data → Use a synthetic sample file*. Tick
**"This dataset is synthetic"**. Its numbers are invented and must never be reported as
findings.

**Real**: download Online Retail II from Kaggle and upload the `.xlsx` unchanged — both
year sheets are read and stacked. `openpyxl` is slow at a million rows, so if you will
process it more than once, convert it first:

```powershell
python scripts/excel_to_csv.py ../data/raw/online_retail_II.xlsx
```

---

## Every day after that

Docker Desktop must be running first — wait for the whale icon to settle.

```powershell
docker start retailpulse-db
docker ps

cd backend
.\.venv\Scripts\Activate.ps1
uvicorn app.main:app --reload
```

Second terminal:

```powershell
cd frontend
npm run dev
```

**Use `docker start`, not `docker compose up`,** if the repository folder has been
renamed since the container was created: Compose derives its project name from the
folder, so it will try to create a second container and fail on the name conflict.

Sign in fresh. **Access tokens last 60 minutes**, and an expired one shows up as a 401 on
`/auth/me` rather than as a visible error.

---

## Before a demonstration or a recording

**Click through every page once.** Analyses are cached after the first computation, and
cold they are slow: features 13.6s, baskets 10.8s, distributions 10.5s, rfm 5.9s,
seasonality 3.6s, series-profile 2.3s. Warm, they are instant. These figures come from
`analysis_results.computed_ms`, which the application records itself.

**Do not use Swagger for the RFM endpoint.** Swagger UI renders the whole response body
into the DOM with syntax highlighting, and that response is 1.5 MB. It will freeze the
browser tab. To fetch a large response, stream it to disk instead:

```powershell
$pw = [System.Net.NetworkCredential]::new('', (Read-Host 'Password' -AsSecureString)).Password
$r  = Invoke-RestMethod 'http://localhost:8000/api/v1/auth/login' -Method Post -Body @{ username = '<email>'; password = $pw }
$h  = @{ Authorization = "Bearer $($r.access_token)" }
Invoke-WebRequest "http://localhost:8000/api/v1/datasets/<id>/analytics/rfm" -Headers $h -OutFile rfm.json
```

Note that `Invoke-WebRequest` is slow at materialising large payloads and is **not** a
way to measure API latency — it measures the client. Use
`backend/scripts/measure_latency.py` for that.

---

## Tests

```powershell
cd backend
pytest                    # all 637
pytest tests/unit         # pure pipeline tests, no database needed
pytest -m db              # only the tests that use PostgreSQL
```

```powershell
cd frontend
npm run test:run          # 280 tests across 26 files
```

Tests needing the database are skipped with a message if `TEST_DATABASE_URL` is
unreachable, so `pytest` always runs to completion.

---

## Useful operations

**Inspect the analysis cache.** Keyed on
`(dataset_id, analysis_type, params_hash, pipeline_version)`:

```powershell
docker exec retailpulse-db psql -U retailpulse -d retailpulse -c "SELECT analysis_type, pipeline_version, computed_ms, created_at FROM analysis_results ORDER BY analysis_type;"
```

**Force one analysis to recompute.** `pipeline_version` is a single string for the whole
pipeline, so changing one analytics module does not invalidate its cached result. After
such a change the API will keep serving the old result, reporting `hit: true` and a
healthy `computed_at`. Delete the row:

```powershell
docker exec retailpulse-db psql -U retailpulse -d retailpulse -c "DELETE FROM analysis_results WHERE analysis_type = 'features';"
```

**Measure API latency** against the three-second target:

```powershell
python scripts/measure_latency.py --dataset-id <uuid> --repeats 30
```

Writes a timestamped directory under `artifacts/performance/`. See its README for what
previous runs found.

---

## When it goes wrong

| Symptom | Cause and fix |
|---|---|
| `JWT_SECRET_KEY is not set` | Generate one into `.env`. |
| `ECONNREFUSED` in the Vite terminal | The backend is not running. It is a separate program in its own terminal. |
| `connection refused` on the database port | The container is not running: `docker start retailpulse-db`. |
| `password authentication failed for user "retailpulse"` | Another PostgreSQL owns the port. Republish the container and update both URLs in `.env`. |
| Container name conflict on `docker compose up` | The folder was renamed. Use `docker start retailpulse-db`. |
| `No 'script_location' key found` | You are not in `backend/`. Every project command runs from there. |
| `alembic: command not found` | The virtual environment is not active. |
| `Activate.ps1 is not recognized` | PowerShell will not run a script from the current directory by name. Use `.\.venv\Scripts\Activate.ps1`. |
| `ALTER SYSTEM cannot run inside a transaction block` | `psql -c` wraps multiple statements in a transaction. Use one `-c` per statement. |
| Tests say the test database is unreachable | `docker compose exec db createdb -U retailpulse retailpulse_test`. |
| Upload returns 413 | Over `MAX_UPLOAD_MB` in `.env`, default 200. |
| An `.xlsx` upload takes minutes | `openpyxl` at this scale. Convert once with `scripts/excel_to_csv.py`. |
| An endpoint returns 409 `CAPABILITY_UNAVAILABLE` | The dataset has no column for that analysis. Online Retail II has no category column. |
| The browser shows a stale analysis after reprocessing | The cache is cleared on reprocess, so this would be a bug. Report it. |
| Swagger freezes | The RFM response. See above. |
