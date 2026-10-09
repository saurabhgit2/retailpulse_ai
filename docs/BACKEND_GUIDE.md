# RetailPulse AI — Backend guide (Phases 2–3)

A walkthrough of the `backend/` folder, written so you can rebuild it. Each part follows the same
structure:

> **What we are building · Why this way · Files · How it works · How to verify · What to learn**

**Scope:** accounts, CSV upload, column detection and mapping, validation, the twelve-step cleaning
pipeline, bulk storage and the data-quality report. That is exactly what the frontend already
expects, so switching `VITE_USE_MOCK_API` to `false` turns the mock off and the real system on.
Analytics (Phase 4), forecasting (Phase 5), segmentation and rules (5b) and the AI layer (Phase 6)
come later; nothing here blocks them.

---

## 0. Quick start

```powershell
docker compose up -d db                                   # PostgreSQL 16
docker compose exec db createdb -U retailpulse retailpulse_test
cd backend
python -m venv .venv ; .\.venv\Scripts\Activate.ps1
pip install -r requirements-dev.txt
Copy-Item .env.example .env                               # then paste a JWT_SECRET_KEY
alembic upgrade head
uvicorn app.main:app --reload
```

Open http://localhost:8000/docs. Then set `VITE_USE_MOCK_API=false` in `frontend/.env`, restart
`npm run dev`, register an account and upload
`data/sample/SYNTHETIC_retail_sales.csv` (generate it with
`python scripts/generate_synthetic_data.py`).

---

## 1. Configuration and project setup

### What we are building
One place that holds every value which differs between machines, validated at start-up.

### Why this way
Hard-coded database URLs and secrets are the two commonest ways a student project fails its
security review. `pydantic-settings` reads `.env`, converts types and fails immediately on a typo,
rather than producing a confusing error hours later.

### Files
`app/core/config.py` · `.env.example` · `requirements.txt` · `pyproject.toml` · `docker-compose.yml`

### How it works
```python
class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=BACKEND_ROOT / ".env")
    database_url: str = "postgresql+psycopg://..."
    max_upload_mb: int = 200
```
`get_settings()` is wrapped in `@lru_cache`, so the file is read once and every caller shares one
object. `require_jwt_secret()` refuses to sign a token when the key is empty instead of quietly
using `""`.

**Docker Compose runs only PostgreSQL**, not the app. You debug Python natively with breakpoints
and reload, while the one piece of infrastructure is identical on every machine.

### How to verify
`docker compose up -d db` then `curl http://localhost:8000/api/v1/health` → `{"status":"ok","database":"up"}`.

### What to learn
Environment variables vs configuration files; why `.env` is git-ignored and `.env.example` is not;
dependency pinning (`~=` allows patches, not minor upgrades); virtual environments.

---

## 2. Errors: one shape, always

### What we are building
Every deliberate failure becomes `{"error": {"code", "message", "details", "request_id"}}`.

### Why this way
The frontend already understands this envelope (it is what the mock produced). One shape means the
client has one error path, and `code` lets it branch — `DATE_FORMAT_REQUIRED` opens the date
picker, `MISSING_REQUIRED_FIELD` highlights the mapping table.

### Files
`app/core/errors.py` · `app/api/error_handlers.py` · `app/core/logging.py`

### How it works
Services raise `ValidationFailed`, `NotFound`, `Conflict`, `Unauthorized`… Each carries an HTTP
status and a code, but knows nothing about HTTP itself; the handler in `error_handlers.py` does the
translating. Two handlers matter beyond the obvious:

* `RequestValidationError` — FastAPI's own 422 body looks nothing like ours, so it is reshaped.
  Without this the frontend would have to understand two formats.
* the catch-all `Exception` handler — logs the traceback and returns a generic message with a
  request ID. Stack traces, SQL and file paths never reach the browser.

Every request gets a short ID (a `ContextVar`, so concurrent requests don't mix), which appears in
each log line for that request and in the error body. A user quotes the ID; you grep the log.

### How to verify
`tests/api/test_auth.py::test_short_passwords_are_rejected_with_our_error_shape` asserts the shape,
not just the status.

### What to learn
Exception hierarchies; separating transport concerns from domain logic; `ContextVar`; why user
messages and log messages are different things.

---

## 3. Passwords and tokens

### What we are building
Registration, sign-in, and a signed token that proves who you are on later requests.

### Why this way
- **Argon2id** for passwords: deliberately slow and memory-hard, so a stolen database is expensive
  to attack. Hashing is one-way; the server can check a password but never recover it.
- **JWT** for sessions: the token carries the user ID and an expiry, signed with `JWT_SECRET_KEY`.
  Anyone can *read* the payload — it is base64, not encryption — but only the server can produce a
  valid signature, so it cannot be forged. Never put anything secret in it.

### Files
`app/core/security.py` · `app/api/routes/auth.py` · `app/api/deps.py` · `app/schemas/auth.py`

### How it works
`hash_password` → store; `verify_password` → compare. `create_access_token(user_id)` returns the
token and its lifetime; `decode_access_token` returns the payload or `None` (never raises at the
call site). `get_current_user` is a dependency: any route that declares `user: CurrentUser` is
protected, and one that doesn't, isn't. The rule lives in the signature where a reviewer can see it.

Login and registration are written so they cannot be used to discover accounts: a wrong password
and an unknown email return the same 401 with the same message.

### How to verify
`tests/unit/test_security.py` (hashing is salted, forged and expired tokens are rejected) and
`tests/api/test_auth.py` (the two failures look identical).

### What to learn
Hashing vs encryption; salts; what a JWT can and cannot protect; why `Depends` is better than an
`if` at the top of every handler.

---

## 4. The database layer

### What we are building
Six tables, two migrations, and the queries that reach them.

### Why this way
- **SQLAlchemy 2.0 ORM** gives typed models and parameterised SQL, which removes SQL injection as a
  class of bug.
- **Alembic migrations** are version control for the schema: a colleague runs `alembic upgrade head`
  and gets exactly your tables. `Base.metadata.create_all()` cannot evolve a database that already
  has data in it.
- **Two migrations, not one** (`0001` users and datasets, `0002` the cleaned data), because the
  schema grows with the phases and the history should show that.

### Files
`app/db/base.py` · `app/db/session.py` · `app/db/models/*.py` · `alembic/versions/*.py` ·
`app/db/repositories/*.py`

### How it works
**Normalisation.** Products, customers and categories are stored once per dataset and referenced by
ID, so a million repeated description strings become a few thousand rows.

**JSONB where it earns its place.** The column profile, the confirmed mapping, the cleaning options
and the quality report are written once, read whole, and never filtered by an inner key. A table
per document would mean six more tables and several joins for no query benefit. Their shape is
still validated — by Pydantic, on the way in and out.

**Indexes chosen from the queries, not from habit** (architecture §8.3). Every analytics query
filters by dataset, then by a date range, so `(dataset_id, occurred_at)` is the workhorse. Guest
rows have no customer, so the customer index is *partial*:
```sql
CREATE INDEX ... ON sales_records (dataset_id, customer_id) WHERE customer_id IS NOT NULL;
```
Each index costs write time and disk on a million-row table, which is why there are five and not
fifteen.

**Sessions.** One `Session` per request is a unit of work: it collects changes and writes them in
one transaction. `get_db` in `deps.py` yields it and commits or rolls back afterwards — the
generator's `finally` block always closes it, even when the endpoint raises.

### How to verify
`alembic upgrade head` then `alembic downgrade base` and up again: migrations must be reversible.
In `psql`, `\d sales_records` lists the indexes and foreign keys.

### What to learn
ORM vs raw SQL; unit of work; migrations; normalisation and when to break it; composite indexes and
the leftmost-prefix rule; `ON DELETE CASCADE`.

---

## 5. The pure core: field guide, dates, detection, validation

### What we are building
The rules of the system, as plain Python: what fields exist, how dates are read, how columns are
guessed, and what the server refuses.

### Why this way
`app/preprocessing/` imports **no web framework and no ORM**. That is checked, not just intended.
It means these modules can be tested with a five-row DataFrame in milliseconds, and reused
unchanged by the research scripts in Phase 5 — which is what makes the numbers in your report and
the numbers in the app the same numbers.

### Files
`field_guide.py` · `dates.py` · `schema_detection.py` · `validation.py` · `csv_io.py`

### How it works
**The field guide is the single source of truth.** Canonical fields, their synonyms, and capability
rules like:
```python
{"key": "segmentation", "requires_all": ["customer_id", "invoice_id", "occurred_at"],
 "requires_one_of": [["revenue"], ["quantity", "unit_price"]]}
```
`GET /datasets/field-guide` serves them and the frontend only *evaluates* them, so adding a field
is a one-file change on the server.

**Dates never get guessed.** Only explicit format patterns are tried, never pandas' free inference
(which can parse different rows by different rules in the same column). If day-first and month-first
both fit — a column whose days never exceed 12 — the API returns `DATE_FORMAT_REQUIRED` and the user
chooses. This is the single most damaging silent error a data pipeline can make.

**Detection checks contents, not just names.** A column called "Price" full of words is left
unmapped with a `TYPE_MISMATCH` warning. The threshold is 95%: a column that cannot be read reliably
is not a date column.

**Reading the file.** `csv_io.read_csv` tries UTF-8, then UTF-8-with-BOM, then Latin-1, because
retail exports are often Windows-encoded and a single pound sign otherwise kills the upload. Every
column is read as text and converted later, so pandas cannot decide a product code is a number and
drop its leading zeros. Only the mapped columns are read — less memory and faster on a 100 MB file.

### How to verify
`pytest tests/unit` — 44 tests covering exactly these rules.

### What to learn
Pure functions and why they are easy to test; data-driven design (rules as data, not `if`s);
character encodings; pandas dtypes; the difference between detection and validation.

---

## 6. The cleaning pipeline

### What we are building
Twelve ordered steps that turn a raw file into trustworthy rows, and explain everything they did.

### Why this way
The brief requires that nothing is changed silently. So every step returns an `ActionRecord` —
what it did, how many rows, why, with examples — and those records *are* the data-quality report.

### Files
`app/preprocessing/cleaning.py` (the steps) · `tests/unit/test_cleaning.py`

### How it works
| # | Step | What it does |
|---|---|---|
| 1 | Normalise text | Trim, upper-case product codes, repair IDs like `13085.0` |
| 2 | Parse types | Dates in the chosen format, numbers; unreadable rows excluded |
| 3 | Exact duplicates | Removed (configurable), with the caveat recorded |
| 4 | Non-merchandise | Postage, fees, adjustments excluded |
| 5 | Invalid prices | Zero or negative unit price excluded |
| 6 | Returns | **Flagged, kept** — net revenue needs them |
| 7 | Missing customer IDs | **Kept as guests** — the sale is still real |
| 8 | Canonical product names | One name per code (the most frequent), variants counted |
| 9 | Revenue | Derived when absent; cross-checked when present |
| 10 | Outliers | **Flagged, never removed** (robust z-score per product) |
| 11 | Partial periods | Last complete week and month recorded |
| 12 | Closure calendar | Weekdays that never trade, and gaps, reported |

Two invariants hold it together:

**Conservation.** `rows in file = rows kept + rows excluded`. It is computed, returned in the
report, asserted in the tests, and re-checked in the background job before anything is stored. If a
step ever drops a row without recording it, that check fails.

**Reproducibility.** `_fingerprint()` hashes the cleaned data in a way that does not depend on row
order, so the same file with the same mapping and pipeline version always produces the same
`clean_data_sha256` — architecture NFR-03 becomes a check rather than a promise.

Two decisions worth defending in your report:

* *Flag, don't delete.* Returns, guests and outliers stay in the data with a boolean. A large
  wholesale order is real; deleting it would understate revenue. Each analysis decides what to
  exclude, and the flag makes that choice visible.
* *The robust z-score.* Outliers are measured with the median and MAD rather than the mean and
  standard deviation, because the outliers themselves inflate a mean-based threshold. When more
  than half a product's rows are identical the MAD is zero, so the code falls back to the scaled
  mean absolute deviation — a case a test caught (see §13).

### How to verify
```powershell
pytest tests/unit/test_cleaning.py -v
```
Then upload the synthetic file and read the report: every step, count and reason is on the screen.

### What to learn
Vectorised pandas (masks instead of loops); dataclasses; keeping an audit trail; invariants as
tests; why a pipeline step must run its predicate once (see the bug in §13).

---

## 7. Storing a million rows

### What we are building
The path from a cleaned DataFrame to rows in PostgreSQL.

### Why this way
Inserting a million rows through the ORM means a million round trips: minutes at best. PostgreSQL's
`COPY` streams them in one go.

### Files
`app/db/repositories/sales.py`

### How it works
Products, customers and categories go through ordinary bulk inserts, because we need their
generated IDs back to point the sales rows at them. Then the sales frame is written as CSV in
100,000-row chunks into:
```sql
COPY sales_records (dataset_id, invoice_id, occurred_at, ...) FROM STDIN WITH (FORMAT csv, NULL '')
```
`COPY` is a PostgreSQL protocol feature rather than SQL the ORM can emit, so the code reaches past
SQLAlchemy to the psycopg connection (`session.connection().connection.driver_connection`).
`NULL ''` makes an empty field a NULL, which is how a guest sale ends up with no customer.

**Measured in this sandbox on PostgreSQL 16:** 1,067,371 rows (Online Retail II's row count) loaded
in **25 seconds**, indexes included, from a 110 MB CSV. Deleting the dataset — one `DELETE`, with
every derived row removed by cascade — took about 60 seconds, which is worth knowing before you
demonstrate a delete live.

### How to verify
Upload Online Retail II, then in `psql`:
```sql
SELECT count(*) FROM sales_records;
EXPLAIN ANALYZE SELECT date_trunc('week', occurred_at), sum(revenue)
FROM sales_records WHERE dataset_id = '...' GROUP BY 1;
```
The plan should show `Bitmap Index Scan on ix_sales_records_dataset_id_occurred_at`. It did here.

### What to learn
Bulk loading; why round trips dominate; `io.StringIO`; how an ORM can be stepped around without
being abandoned; reading a query plan.

---

## 8. Background processing

### What we are building
Upload answers immediately; cleaning happens afterwards; the client polls for the result.

### Why this way
Cleaning a million rows takes far longer than a browser will wait. `POST /process` validates
everything it can *synchronously* (so mistakes come back at once), sets the status to `processing`,
returns **202 Accepted**, and queues the work. The frontend polls `GET /datasets/{id}` until the
status is `ready` or `failed` — which is exactly what `usePolling` in the frontend already does.

### Files
`app/services/dataset_service.py` · `app/services/processing_service.py` ·
`app/api/routes/datasets.py`

### How it works
`process_dataset(dataset_id)` opens its **own** session: it runs after the response, so the
request's session is long gone. It reads only the mapped columns, cleans, re-checks conservation,
stores, and writes the report. Every failure path ends on the dataset row: expected errors become
the `status_message` the user reads; unexpected ones are logged in full and reported as a safe
sentence.

**The honest limitation.** `BackgroundTasks` runs inside the API process, so a restart loses
running jobs. Rather than leaving a dataset "processing" for ever, `recover_stuck_datasets()` runs
at start-up and marks them failed with an explanation. When this needs to survive restarts, the
upgrade is a real queue (RQ or Celery) — the architecture records that as ADR-03, and the service
boundary here is what makes it a small change.

### How to verify
`tests/integration/test_upload_flow.py` walks upload → mapping → processing → report. Manually:
upload, watch the status change, then restart `uvicorn` mid-processing and see the dataset marked
failed with a reason instead of hanging.

### What to learn
202 vs 200; polling vs websockets; why a background job needs its own session; designing for
failure rather than assuming success.

---

## 9. The API layer

### What we are building
Ten endpoints, each a handful of lines.

### Why this way
Routes do HTTP only: validate the request, call one service, return a schema. Business logic lives
in services, SQL in repositories, rules in the pure core. A route you can read in ten seconds is a
route you can review.

### Files
`app/main.py` · `app/api/deps.py` · `app/api/routes/*.py` · `app/schemas/*.py`

### How it works
```python
@router.post("", response_model=DatasetDetail, status_code=201)
def upload_dataset(session: DbSession, user: CurrentUser, settings: AppSettings,
                   file: Annotated[UploadFile, File()], is_synthetic: Annotated[bool, Form()] = False):
```
Everything in that signature is doing work:

* `@router.post(...)` is a **decorator**: it registers the function with FastAPI and returns it
  unchanged. `response_model` both filters the response and documents it.
* the **type hints are the contract**. FastAPI reads them to parse the request, convert types,
  validate, and generate the OpenAPI docs at `/docs`. A wrong type is a 422 before your code runs.
* `DbSession`, `CurrentUser`, `AppSettings` are **dependencies** — `Annotated[X, Depends(f)]`.
  FastAPI calls `f`, passes the result in, and runs any cleanup afterwards. That is how the session
  closes and how "this route needs a signed-in user" is declared rather than remembered.

Two details worth copying: static routes (`/datasets/template`, `/datasets/field-guide`) are
declared **before** `/datasets/{dataset_id}`, or "template" would be read as an ID; and the
ownership check is a dependency (`OwnedDataset`) so a new endpoint cannot forget it.

**Sync, not async** (architecture ADR-02). pandas, psycopg and the cleaning code are synchronous
and CPU-bound. FastAPI runs `def` endpoints in a thread pool, so they don't block the event loop,
and the code stays easy to read and debug. `async def` here would add complexity and no throughput.

### How to verify
Open http://localhost:8000/docs and drive the whole flow from the browser — that page is generated
from the schemas, so if it looks right, the contract is right.

### What to learn
Decorators; type hints as a contract; dependency injection; request parsing (JSON vs form vs
multipart); status codes; OpenAPI.

---

## 10. Tests

| Suite | What it protects | Needs a database |
|---|---|---|
| `tests/unit/test_dates.py` | dd/mm vs mm/dd, impossible dates, ambiguity, complete periods | no |
| `tests/unit/test_schema_detection.py` | Online Retail II maps correctly; contents override names | no |
| `tests/unit/test_field_guide.py` | Capability rules, including the revenue-or-parts rule | no |
| `tests/unit/test_validation.py` | Everything the API refuses, and with which code | no |
| `tests/unit/test_cleaning.py` | Conservation, each exclusion reason, flags, fingerprint, outliers | no |
| `tests/unit/test_security.py` | Salted hashes, forged and expired tokens | no |
| `tests/api/test_auth.py` | Registration, login, identical failure messages, protected routes | yes |
| `tests/api/test_datasets.py` | Upload rules, mapping errors, ownership (404 not 403), delete | yes |
| `tests/integration/test_upload_flow.py` | Upload → map → process → report, with real numbers | yes |

Database tests run inside a transaction that is rolled back afterwards, so they cannot affect each
other, and they **skip with a message** if the test database is unreachable — `pytest` always runs.

---

## 11. Python and FastAPI concepts, shown in this code

| Concept | Plain explanation | Where |
|---|---|---|
| **Decorator** | A function that wraps another and returns it, adding behaviour. `@router.get(...)` registers a route; `@lru_cache` remembers a result. | `routes/*.py`, `config.py` |
| **Type hints** | Annotations that FastAPI and Pydantic read to parse and validate data. Not just documentation here — they run. | everywhere |
| **Dependency injection** | Declaring what you need; the framework supplies it. Makes tests trivial: override the dependency. | `api/deps.py` |
| **Generator + `yield`** | A function that pauses. `get_db` yields the session, then the code after `yield` runs as cleanup. | `deps.py`, `session.py` |
| **Context manager (`with`)** | Guarantees cleanup — the file closes, the COPY finishes — even when an exception is raised. | `dataset_service.py` |
| **Dataclass** | A class that is just fields, with `__init__` written for you. | `ActionRecord` |
| **Pydantic model** | A class that validates and converts data at the boundary of the system. | `schemas/` |
| **ORM model** | A class mapped to a table; instances are rows. | `db/models/` |
| **Session / unit of work** | Collects changes and commits them as one transaction. | `deps.get_db` |
| **Exception hierarchy** | Domain errors carry meaning; one handler turns them into HTTP. | `core/errors.py` |
| **Vectorised pandas** | Whole-column operations instead of row loops: shorter and orders of magnitude faster. | `cleaning.py` |
| **`ContextVar`** | A variable with a separate value per request, even across threads. | `core/logging.py` |

---

## 12. Where the complexity really is

- **The cleaning pipeline's ordering.** Steps depend on each other: types must be parsed before
  prices can be compared, duplicates removed before counts mean anything. Changing the order changes
  the numbers, so the order is part of `pipeline_version`.
- **The COPY path.** It steps outside the ORM and formats data by hand, which is exactly where type
  mismatches bite (see §13). Read it carefully before changing it.
- **Background work.** Nothing about the request is available there: no user, no session, no
  settings from the request. Everything the job needs must already be on the dataset row.
- **pandas nullability.** `NA` in an integer column silently makes it a float. That is the source
  of more data bugs than any other single thing in Python data work.

---

## 13. What was verified, and what you must run

The sandbox where this was written has no package index, so **FastAPI, SQLAlchemy, Alembic, psycopg,
argon2 and pytest could not be installed there**. What was done instead:

- **Every file byte-compiled** (58 Python files), and a static check confirms
  `app/preprocessing/` imports no web framework or ORM, and that every internal `app.*` import
  resolves.
- **44 pure-logic tests run and pass** (dates, detection, field guide, validation, cleaning) using a
  small pytest-compatible runner. The whole pipeline was also run end to end on a generated
  synthetic file: 4,436 rows → 4,268 kept, 168 excluded, conservation holding.
- **The schema was created on a real PostgreSQL 16 server** in the sandbox and inspected: all
  constraints, foreign keys and the five indexes (including the partial one) are valid.
- **The bulk-load path was exercised at Online Retail II scale**: 1,067,371 rows through `COPY` in
  25 seconds, NULLs and booleans preserved; a weekly aggregation used
  `ix_sales_records_dataset_id_occurred_at` as designed; cascade delete removed every derived row.

> **Two real bugs this found.**
> 1. *The COPY rejected every row*: `frame["customer_id"].map(ids)` returns float64 when any value
>    is missing (pandas upcasts), so the CSV contained `3436.0` and PostgreSQL refused it for a
>    `bigint`. Fixed by casting to the nullable `Int64` dtype.
> 2. *Outliers were never flagged for a product whose quantities are all identical*: the MAD is
>    then 0 and the score is undefined. Fixed with a scaled mean-absolute-deviation fallback.
>
> Both were found by testing at realistic scale and with an awkward fixture — not by reading the
> code.

### 13.1 First run on a real machine — 2026-09-30

Everything above was done without a running framework. The first execution on a Windows machine
with FastAPI, SQLAlchemy, Alembic, psycopg and pytest actually installed found **five** further
defects, every one of them in a place that only exists when the framework starts. Final state:

```
68 passed, 0 failed
```

| # | Symptom | Cause | Fix |
|---|---|---|---|
| 1 | `SettingsError: error parsing value for field "cors_origins"` at start-up | pydantic-settings treats a `list[str]` field as complex and JSON-decodes the raw `.env` value **before** any validator runs, so `CORS_ORIGINS=http://localhost:5173` never reached `_split_origins` | `Annotated[list[str], NoDecode]` on the field; the validator now accepts both the comma and JSON forms |
| 2 | `AssertionError: Status code 204 must not have a response body` while registering routes | `-> None` on the delete route becomes a response model (`NoneType`), which FastAPI refuses to pair with a 204 | declare `response_class=Response` and return a bare `Response(status_code=204)` |
| 3 | Integration tests: `Dataset ... is not awaiting processing; skipping` | the background job opens its own session, correctly for production — but in tests that means the *development* database, where the row created inside the test's uncommitted transaction does not exist | job opens its session through `_open_session()`; the `client` fixture substitutes the test's transaction-scoped session, wrapped so `close()` is a no-op |
| 4 | `KeyError: 'clean_data_sha256'` | the reproducibility fingerprint was stored on the row but never exposed in `DatasetSummary` | added the field to the schema (it is evidence for NFR-03, so it belongs in the API); replaced the near-tautological assertion with one that checks 64 hexadecimal characters |
| 5 | `assert 0 == 1` on `rows_guest` | in the fixture the only row with a blank customer ID was *also* the zero-price row, excluded at step 5 — so step 7 could never produce a guest | gave the fixture its own valid guest row. One row, one concern |

Two of those (1, 2) were in the application; three (3, 4, 5) were in the tests or the schema around
it. In all three of the latter, **the pipeline was right and the test was wrong** — worth
remembering that a red test is a disagreement between two claims, not proof that the code is the
mistaken one.

The honest lesson for the write-up: byte-compiling proves syntax, and pure-logic tests prove the
analytics. Neither says anything about what a framework does with your declarations at import time,
or about what a background task can see from inside a transaction. Those need the framework
running, and until it ran, that part of the system was unverified however carefully it was written.

### 13.2 Still not run

```powershell
ruff check .        # linting
```
Version pins use `~=`, so pip may resolve newer patches than were assumed. If `pip install` ever
reports a conflict, that is worth reporting rather than working around.

---

## 14. Suggested commits

1. `feat(backend): FastAPI app factory, settings, logging and error envelope`
2. `feat(backend): database session, models and Alembic migrations`
3. `feat(auth): registration, login and JWT dependencies`
4. `feat(preprocessing): field guide, date handling and column detection`
5. `feat(preprocessing): validation rules`
6. `feat(preprocessing): twelve-step cleaning pipeline with conservation check`
7. `feat(datasets): upload, mapping confirmation and background processing`
8. `feat(db): bulk load with COPY`
9. `test(backend): unit, API and integration tests`
10. `docs(backend): setup and walkthrough`

---

## 15. Phase 4 — analytics and entropy

### What we are building

Twelve read-only endpoints under `/datasets/{id}/analytics/`, plus
`/datasets/{id}/filter-options`. Together they answer the §12.5 EDA catalogue: what the headline
numbers are, how they move over time, where revenue comes from, how the distributions are shaped,
what the relationships look like, which features carry information about demand, and which periods
are unusual.

### Why this way

**PostgreSQL aggregates; pandas analyses.** A million sales rows become a few hundred weekly totals
in the database, and only those cross into Python. Every query starts with `dataset_id` then a date
range, which is the leading edge of the composite index built in Phase 3. The one exception is
`distributions`, which needs the values themselves for quantiles and a histogram — so it pulls one
column (about 8 MB per million rows) and the result is cached.

**`app/analytics/` is pure.** No FastAPI, no SQLAlchemy — checked, not just intended. That is what
lets `scripts/profile_dataset.py` import the same functions and produce the figures for your report
directly from a file. The report and the dashboard cannot disagree, because they run the same code.

### Files

| Module | What it does |
|---|---|
| `analytics/kpis.py` | The §12.4 definitions, Gini and Pareto concentration |
| `analytics/trends.py` | Time series, moving average, growth, partial-period flags, `week_start` |
| `analytics/breakdowns.py` | Ranked products / regions / categories with Pareto shares |
| `analytics/distributions.py` | Histograms, percentiles, skew, Tukey and robust-z outlier counts |
| `analytics/seasonality.py` | Calendar indices and a classical decomposition |
| `analytics/relationships.py` | Pearson *and* Spearman, price-elasticity proxy, discount proxy |
| `analytics/statistics.py` | Mann-Whitney / Kruskal-Wallis with effect sizes |
| `analytics/entropy.py` | Shannon entropy, mutual information, symmetric uncertainty |
| `analytics/features.py` | Lagged feature table, two MI estimators, rank agreement |
| `analytics/series_profile.py` | ADI, CV², intermittency class, spectral entropy |
| `analytics/anomalies.py` | Robust baseline and explained anomalies |
| `db/repositories/analytics.py` | The aggregation SQL and the shared filter builder |
| `db/models/analysis.py`, `alembic/versions/0003_*` | The result cache |
| `services/analytics_service.py` | Fetch, compute, cache; capability and readiness checks |
| `api/routes/analytics.py`, `schemas/analytics.py` | The endpoints and the shared filter dependency |

### How it works — the parts worth defending

**Growth is withheld rather than guessed.** A KPI comparison is only computed when both windows are
the same length and both complete; otherwise every growth figure is `null` with a note. Comparing a
part week against a whole one manufactures a decline.

**A KPI with no source column is hidden, not zero.** No invoice column means no order count, so AOV
is `null`. `None` and `0` are different claims.

**Entropy is implemented from the definitions** (§12.7), because the report has to explain them. The
tests check hand-calculable values — a fair coin is exactly 1 bit, four equal categories exactly 2.
Mutual information is reported at 3, 5 and 10 target bins, because binning changes the answer and
presenting one number would hide that. Identifier-like columns are never ranked: MI is biased
towards high cardinality, and a unique ID has maximal MI and zero generalisation.

**Non-parametric tests with effect sizes.** Retail distributions are nowhere near normal, so
Mann-Whitney and Kruskal-Wallis replace t-tests and ANOVA. Above 10,000 rows the response carries a
warning that at that size almost any difference is "significant" and the effect size is what to
read. Normality is reported as shape statistics rather than a hypothesis test, for the same reason.

**Anomaly detection is all medians, and that is the whole design.** This module took four attempts,
and each failure is now a test:

1. *A mean-based scale divided by numerical dust.* With two cycles of history a 52-phase seasonal
   component fits the noise, the remainder collapses to zero, and ordinary weeks came back as
   10¹⁵-sigma events. Fixed with a floor on the scale relative to the series' own spread.
2. *Too few cycles for any seasonal claim.* Measured on noise containing no anomaly at all, a
   52-phase basis flagged **47%** of periods at 2.3 cycles and **14%** at 4, against 0.2% at 10. The
   detector now needs eight cycles before it will subtract a seasonal profile; below that it removes
   the trend and claims nothing about seasonality.
3. *A moving-average trend spread one spike across a year*, and a *mean* seasonal profile let one
   extreme week reshape its own week-of-year — so a single real event invented anomalies a year
   either side of itself. Both baselines are now medians, which do not move until half the data is
   anomalous.
4. *Additive seasonality could not track multiplicative growth.* December at 3× the level with a
   rising trend flagged nearly every December. The baseline is now a ratio when the series is
   strictly positive, and residuals are scored proportionally. Finally, the seasonal phase comes
   from the **calendar**, not the row number: `index % 52` drifts about a week a year, so after a
   decade December sits in a different slot. False-positive rate on clean seasonal data: 9.8% → 1.7%.

**A pandas trap worth knowing.** `to_period("W-MON")` means the week *ending* Monday, so its
`start_time` is a **Tuesday**. Only `W-SUN` gives Monday starts, which is what PostgreSQL's
`date_trunc('week')` produces. Getting this wrong does not raise — a `date_range(freq="W-MON")`
reindex simply matches nothing and returns a full series of zeros. `trends.week_start()` exists so
that trap lives in one place, and a test asserts it.

### How to verify

```powershell
pytest tests/unit          # 152 tests, no database needed
pytest                     # adds the API and integration tests
python scripts/profile_dataset.py ../data/sample/SYNTHETIC_retail_sales.csv --synthetic
```

Then `/docs` → any analytics endpoint → **Try it out**.

### What to learn

Window functions and `GROUP BY date_trunc`; why aggregation belongs in the database; Shannon
entropy and mutual information; non-parametric tests and effect sizes; robust statistics (median,
MAD, breakdown point); classical decomposition and seasonal strength; ADI/CV² intermittency
classes; spectral entropy; cache keys and canonical hashing.

### Phase 3's remaining 15%, also in this release

* **Excel support.** Online Retail II ships as a workbook with a sheet per year. `csv_io.read_table`
  reads both sheets and stacks the ones whose columns match, skipping anything else with a warning.
  `usecols` is applied *after* stacking, because pandas applies it to every sheet and one unrelated
  "Notes" tab would otherwise fail the whole read. openpyxl is slow on a million rows, so
  `scripts/excel_to_csv.py` converts once if you would rather work from CSV.
* **`scripts/profile_dataset.py`** — the EDA deliverable. Reads a file, cleans it, and writes
  `PROFILE.md` plus CSVs: shape and exclusions, KPIs, distributions, seasonality, concentration,
  entropy per categorical feature, and the series forecastability profile.
* **`/datasets/{id}/filter-options`** — date bounds, regions, categories and top products.

### Added after reviewing the literature (6 Oct)

Three additions, each tied to a specific paper rather than to taste:

* **RFM** (`analytics/rfm.py`, `GET /analytics/rfm`). Chen, Sain & Guo (2012), *Journal of Database
  Marketing & Customer Strategy Management* 19(3), 197–208 — the paper behind this dataset —
  aggregate Recency, Frequency and Monetary per customer and then cluster with k-means. This module
  does the aggregation and describes the distributions; the clustering is RQ2, in Phase 5b. It also
  carries that paper's own warning forward: k-means is sensitive to outliers and to variables on
  incomparable scales, so the response names the standardisation decision Phase 5b has to make, and
  flags a strongly skewed monetary distribution as a candidate for a log transform.
  Two differences from the paper to state in the report: it identified customers by **postcode**
  (the public release has `Customer ID`), and it restricted to **UK customers in 2011** — which the
  filter set reproduces without code changes.
* **A deseasonalised series** from the decomposition. Chu & Zhang (2003), *Int. J. Production
  Economics* 86, 217–231, found that prior seasonal adjustment **significantly improved**
  neural-network accuracy on aggregate retail sales, and that the best model overall was a neural
  network fitted to deseasonalised data. Phase 5 can now train on that series directly and compare
  against models fitted to the raw one — a cheap, well-grounded experiment for RQ1.
* **Basket size** (`GET /analytics/baskets`, and a section in the profiling report). Chen et al.
  read 18.3 distinct items per transaction as evidence that this retailer's customers are largely
  organisations rather than individuals — a substantial conclusion drawn from one simple aggregate.

Also worth carrying into Phase 5: Aras, Deveci Kocakoç & Polat (2017), *Journal of Business
Economics and Management* 18(5), 803–832, found that **no single model won across all series** and
that combined forecasts gave statistically significant accuracy gains — direct support for RQ1's
premise and for including a combination in the model ladder. Auppakorn & Phumchusri (2022, MSIE)
compare TBATS, regression and XGBoost on daily SKU sales using **WAPE**, which supports that metric
choice.

### What the supplied literature does *not* support

Checked against the seventeen papers provided, so it is not mistaken for grounded method:

* **Shannon entropy and mutual information for feature analysis** (§12.7). The only occurrence of
  "entropy" in any retail-relevant paper in that set is *classification entropy* as a fuzzy
  clustering validity index — a different concept. The approach may be sound and original, but it
  needs its own references or an explicit framing as the author's contribution.
* **Adjusted Rand Index and segment stability across windows** (RQ2). "Adjusted Rand" does not
  appear at all in the segmentation review; the indices in use there are silhouette,
  Davies–Bouldin, Calinski–Harabasz, elbow and the gap statistic.
* **Actionability-ranked association rules** (RQ3). Those papers rank by support, confidence and
  lift. **MASE** appears nowhere; WAPE in one paper only.

### Still open

* **ADF and KPSS stationarity tests** need statsmodels, which arrives in Phase 5 with ETS and ARIMA —
  which is also where differencing decisions are actually made. The endpoint returns
  `stationarity.available = false` with that reason rather than pretending.
* **STL** for the same reason: seasonality currently uses classical decomposition. Seasonal strength
  is defined identically for both, so the measure stays comparable when the switch happens.
* **Model-based feature importance** (XGBoost gain, permutation importance) needs a trained model,
  so §12.7's third comparison completes in Phase 5.

---

## 16. Where Phase 5 plugs in

Small deviations from the architecture document, all deliberate:

* `datasets.profile` (JSONB) was added — the frontend needs the detected columns to rebuild the
  mapping step when resuming or retrying.
* `quantity` is *recommended*, not required, exactly as the §12.1 footnote describes: revenue can
  come from a revenue column instead.
* The upload takes an `is_synthetic` form field, so synthetic data is labelled from the moment it
  arrives.
