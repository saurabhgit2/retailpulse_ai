# RetailPulse AI — Frontend guide (Phase 2–3 foundation)

This guide explains every part of the `frontend/` folder. It is written so you can rebuild it
yourself. Each major part follows the same structure:

> **What we are building · Why this way · Files · How it works · How to verify · What to learn**

The code is in the files themselves (heavily commented); this guide shows only the lines that
matter for understanding.

**Scope of this delivery:** the foundation you chose. That means project setup, styling, the API
layer, a mock API, authentication, routing and layout, the upload wizard, and the data-quality
report, plus tests. Dashboard, analytics, forecasting and AI pages appear in the navigation as
"coming in Phase N" placeholders.

---

## 0. Quick start

```bash
cd frontend
npm install
cp .env.example .env
npm run dev          # http://localhost:5173
npm run test:run     # all tests once
```

Then: **Create one** (account) → **Upload dataset** → **Use a synthetic sample file** →
**Upload and detect columns** → **Confirm mapping and process** → the data-quality report opens.

To try your real data, download Online Retail II from Kaggle and upload the CSV. In mock mode, the
browser reads only the first 1 MB (about 5,000 rows) to build the preview and the report. The real
backend will process the whole file.

---

## 1. Project setup: Vite, React, Tailwind, ESLint, Vitest

### What we are building
A React project that starts a development server, builds for production, checks code style and
runs tests. All of it is configured in a handful of small files.

### Why this way
- **Vite** serves your source files directly to the browser during development (very fast start,
  instant hot reload) and bundles them for production. Create React App is deprecated; Next.js
  adds server rendering you don't need.
- **Tailwind CSS v4** is configured *in CSS* (no `tailwind.config.js`), through one Vite plugin.
- **Vitest** reuses Vite's configuration, so tests understand JSX and imports exactly like the app.
- **ESLint** with the React Hooks plugin catches the most common React bug: breaking the Rules of
  Hooks.

### Files
`package.json` · `vite.config.js` · `eslint.config.js` · `.prettierrc` · `.env.example` ·
`.gitignore` · `index.html` · `src/main.jsx` · `src/App.jsx`

### How it works
1. `index.html` contains `<div id="root">` and loads `/src/main.jsx`.
2. `main.jsx` creates the React root and renders `<StrictMode><BrowserRouter><App/></BrowserRouter></StrictMode>`.
3. `App.jsx` wraps everything in `<AuthProvider>` and renders `<AppRoutes/>`.
4. `vite.config.js` does three jobs:
   ```js
   plugins: [react(), tailwindcss()],              // JSX + Tailwind
   server: { proxy: { '/api': { target: env.DEV_API_TARGET || 'http://localhost:8000' } } },
   test: { environment: 'jsdom', setupFiles: './src/test/setup.js' },
   ```
   The **proxy** is what makes local development CORS-free. The browser only ever talks to
   `localhost:5173`, and Vite forwards `/api/...` to FastAPI.

**Environment variables.** Vite replaces `import.meta.env.VITE_*` with the values from `.env` *at
build time*. They end up in the JavaScript the browser downloads, which is why the `VITE_` prefix
exists: it marks a value as safe to make public. `DEV_API_TARGET` has no prefix and is read only by
`vite.config.js` via `loadEnv(mode, cwd, '')`.

### How to verify
`npm run dev` prints a local URL; `npm run build` creates `dist/`; `npm run lint` should report no
errors.

### What to learn
Module bundling (why the browser needs one); dev server vs production build; what "hot module
replacement" means; build-time vs run-time configuration; why `package-lock.json` must be committed
(it pins the exact versions everyone installs).

---

## 2. Styling system: design tokens and dark mode

### What we are building
One colour palette, defined once, that every component uses, and that switches to dark mode
automatically with the operating system.

### Why this way
Hard-coding `#0d6b63` in 40 components makes a palette change a 40-file edit and makes dark mode
impossible. CSS variables ("tokens") give one place to change.

### Files
`src/index.css`

### How it works
```css
:root { --accent: #0d6b63; --surface: #ffffff; ... }            /* light palette */
@media (prefers-color-scheme: dark) { :root { --accent: #5cc4b6; ... } }
@theme inline { --color-accent: var(--accent); ... }             /* → bg-accent, text-accent */
```
`@theme inline` tells Tailwind to generate utilities (`bg-surface`, `text-muted`, `border-rule`…)
that *point at* the variables. When dark mode changes the variable, every utility follows.
Semantic colours (`ok`, `warn`, `crit`, `info`) are kept separate from the brand accent because they
carry meaning (good, warning, error).

### How to verify
Switch your OS to dark mode: the whole app changes without a reload.

### What to learn
CSS custom properties; the cascade; media queries; utility-first CSS; colour contrast for
accessibility (text must stay readable on both backgrounds).

---

## 3. The API layer: `apiClient.js`, `auth.js`, `datasets.js`

### What we are building
The only code in the frontend that makes HTTP requests. Pages never call `fetch` directly.

### Why this way
- **One place for cross-cutting concerns:** the auth header, the base URL, and error handling.
- **One error shape:** whatever goes wrong (server error envelope, FastAPI validation error,
  network failure), components receive an `ApiError` with `.message`, `.code`, `.status` and
  `.requestId`.
- **Swappable transport:** the mock API and the real backend plug into the same function.

### Files
`src/services/apiClient.js` · `src/services/auth.js` · `src/services/datasets.js`

### How it works
Service files read like an index of the backend:
```js
export function processDataset(datasetId, { mapping, options }) {
  return api.post(`/datasets/${encodeURIComponent(datasetId)}/process`, { mapping, options });
}
```
`request()` in `apiClient.js` then:
1. adds `Authorization: Bearer <token>` if a token exists;
2. encodes the body as JSON, form data (login) or multipart (file upload);
3. sends it through the **transport** (browser `fetch`, or the mock);
4. on a non-2xx response, converts the body into an `ApiError`;
5. on a **401 when a token was sent**, calls `onUnauthorized()` → the user is signed out with
   "Your session has expired". (A 401 *without* a token is just a wrong password.)

**Dependency injection.** The API client must not import React, but it needs the current token.
So `AuthProvider` hands it two functions at start-up:
```js
configureAuth({ getToken: () => tokenRef.current, onUnauthorized: () => signOut('...') });
```
The client depends on an *interface* (two functions), not on React. This is the same idea as
FastAPI's `Depends`, and it's why `apiClient.test.js` can test the client with plain fake functions.

**Why login sends a form, not JSON.** FastAPI's standard OAuth2 password flow
(`OAuth2PasswordRequestForm`) expects `application/x-www-form-urlencoded` with fields `username`
and `password`. `auth.login()` sends the email as `username`.

### How to verify
`src/services/apiClient.test.js` (9 tests): base path, query arrays, bearer token, error envelope,
FastAPI `detail[]` errors, network failure, cancellation, session expiry, 204 responses.

### What to learn
HTTP methods and status codes; request headers; JSON vs form vs multipart bodies; `fetch` and
`Response`; Promises and `async/await`; custom `Error` subclasses; `AbortController`; dependency
injection.

---

## 4. The mock API (`src/services/mock/`)

### What we are building
A fake backend that runs inside the browser, so the frontend can be built and demonstrated before
FastAPI exists.

### Why this way
- **It returns real `Response` objects** from a function with `fetch`'s signature. The rest of the
  app can't tell the difference, so switching to the real backend is one env variable.
- **It follows the API contract in architecture §9**: same paths, status codes (201, 202, 409, 413,
  415, 422…) and error envelope. It acts as an *executable specification* for the backend you
  build in Phase 3: if your FastAPI returns the same shapes, the frontend just works.
- **It is honest.** Everything it produces is labelled Mock (banner on every page, a "Mock report"
  notice), and its reports are computed from preview rows only.

### Files
| File | Role |
|---|---|
| `mockServer.js` | Route table (`method + regex → handler`), latency, auth, errors |
| `mockDb.js` | Users and datasets in localStorage; file previews in memory |
| `fixtures.js` | Field guide (fields + capability rules), template CSV, default options |
| `schemaDetection.js` | Column profiling and mapping suggestion (the §12.1 algorithm) |
| `mockProcessing.js` | 9 of the 12 cleaning steps, with the conservation check |
| `syntheticSample.js` | Seeded generator of a labelled SYNTHETIC CSV with deliberate problems |

### How it works
Upload: `POST /datasets` reads the first 1 MB of the file with `file.slice(0, 1MB).text()`,
parses it with `utils/csv.js`, profiles each column, and suggests a mapping:
1. normalise headers (`"Customer ID"` → `customerid`) and look them up in the synonym lists;
2. only accept the match if the column's *content* fits (a "Price" column full of text is left
   unmapped with a `TYPE_MISMATCH` warning);
3. detect date formats and flag day/month vs month/day **ambiguity**.

Process: `POST /datasets/{id}/process` validates the mapping (unknown columns, duplicates, required
capability, date format), sets `status = processing`, answers **202**, and finishes a few seconds
later with a timer, just as a background task would.

Passwords are hashed with SHA-256 even in the mock. Tokens are unsigned (`mock.<base64 JSON>`) and
must never be copied into real code; the backend will issue signed JWTs.

### How to verify
`schemaDetection.test.js` (Online Retail II headers map correctly; ambiguity and type mismatches are
flagged) and `mockProcessing.test.js` (conservation, one exclusion per problem, returns and guests
flagged not deleted).

### What to learn
Test doubles (mocks and fakes); API contracts; regular expressions; the difference between
*simulating* and *implementing*: the mock is **not** the pipeline. The real one is pandas in the
backend.

> **A bug these tests caught.** The first version of the cleaning step ran its filter predicate
> twice: once to collect removed rows, once to keep the rest. The duplicate check *remembers* rows
> it has seen, so on the second pass it treated every row as a duplicate and deleted everything.
> The conservation test failed immediately. Lesson: a function with hidden state (a "stateful
> predicate") must run exactly once per item. The fix partitions the rows in a single pass.

---

## 5. Custom hooks: `useApi` and `usePolling`

### What we are building
Two reusable pieces of logic for talking to the server from components: "load this when I appear"
and "keep checking until a job finishes".

### Why this way
Without them, every page repeats the same `useEffect` + loading/error state + cancellation code,
and most copies get cancellation wrong.

### Files
`src/hooks/useApi.js` · `src/hooks/usePolling.js`

### How it works
```js
const load = useCallback((signal) => getQualityReport(datasetId, { signal }), [datasetId]);
const { data, error, loading, reload } = useApi(load);
```
- `useCallback` keeps `load` the **same function** until `datasetId` changes. Without it, a new
  function is created every render, the effect sees a "new dependency", and it re-fetches forever.
- Inside `useApi`, the effect creates an `AbortController` and returns a **cleanup function** that
  aborts the request. The cleanup runs when the component unmounts *or* before the effect re-runs.
  So a slow, out-of-date response can never overwrite newer data.
- **StrictMode** mounts every component twice in development to expose effects without cleanup.
  With proper cleanup, the first request is simply cancelled. (The earlier build of this project
  had pages stuck loading because of a "has mounted" guard instead of cleanup.)

`usePolling` chains `setTimeout` calls instead of `setInterval`: the next request is scheduled only
after the previous one returns, so slow responses can't pile up. It stops when `isDone(result)` is
true, on error, or on unmount. `isDone` is kept in a ref so callers can pass an inline function
without restarting the loop.

### How to verify
`usePolling.test.jsx`: it stops after "ready" (exactly 3 calls), stops on unmount, and stops on error.

### What to learn
The effect lifecycle (run → cleanup → run); dependency arrays; stale closures; `useRef` for values
that shouldn't trigger re-renders; race conditions in async UI.

---

## 6. Authentication: `AuthProvider`, route guards, token storage

### What we are building
Sign-up, sign-in, sign-out, "session expired" handling, and pages that only signed-in users can
see.

### Why this way
- **Context** makes "who is signed in" available everywhere without passing props through every
  level.
- The **status** has three values: `checking` (confirming a stored token), `authenticated`,
  `anonymous`. The UI never flashes the login page to someone who is already signed in.
- **Route guards** keep the redirect logic in one place. The login form never navigates;
  `PublicOnlyRoute` redirects as soon as the status becomes `authenticated`, back to the page the
  user originally asked for (`location.state.from`).

### Files
`src/context/auth-context.js` · `src/context/AuthProvider.jsx` · `src/hooks/useAuth.js` ·
`src/components/auth/ProtectedRoute.jsx` · `src/components/auth/PublicOnlyRoute.jsx` ·
`src/pages/LoginPage.jsx` · `src/pages/RegisterPage.jsx` · `src/utils/validation.js`

### How it works
- `signIn` → `POST /auth/login` → token → `GET /auth/me` → store user → status `authenticated`.
- The token lives in state **and** `sessionStorage` (survives a reload, cleared when the tab
  closes). Trade-off (architecture §16): injected scripts (XSS) could read it; an httpOnly cookie is
  stricter but needs CSRF protection. React escapes all rendered text, and tokens expire after
  60 minutes.
- Why is the context object in `auth-context.js` and the provider in `AuthProvider.jsx`? Vite's hot
  reload works best when a component file exports only components.

**Security reminder:** the guards protect the *interface* only. Anyone can call the API directly,
so the backend must reject requests without a valid token. The frontend is never the security
boundary.

### How to verify
`LoginPage.test.jsx` (sends trimmed email; shows the server's error; shows the "session expired"
notice) and `validation.test.js`. Manually: sign in, reload (still signed in), open a new tab
(signed out, because sessionStorage is per tab).

### What to learn
React Context; the Provider pattern; `useMemo` for stable context values; controlled forms;
`event.preventDefault()`; password hashing vs encryption (backend, Phase 2); JWT structure.

---

## 7. Routing, layout, and the URL as source of truth

### What we are building
Every URL in the app, a shared frame (sidebar and top bar), and navigation that adapts to the
selected dataset.

### Why this way
- **Nested routes:** all signed-in pages sit inside one `<Route element={<ProtectedRoute><AppShell/></ProtectedRoute>}>`,
  and `<Outlet/>` in `AppShell` shows the current page. Authentication and layout are declared once.
- **The URL decides the current dataset** (`/datasets/:datasetId/quality`), not a state variable.
  Reload, the back button and shared links all work for free. `DatasetProvider` reads it with
  `useMatch('/datasets/:datasetId/*')`.
- **Capability-driven navigation:** pages the dataset can't support (e.g. Customers without a
customer ID column) are shown disabled with the reason. This is the "don't show irrelevant charts"
  rule from the brief, implemented from data the backend provides.

### Files
`src/routes.jsx` · `src/components/layout/*` · `src/context/DatasetProvider.jsx` ·
`src/hooks/useDatasets.js` · `src/content/plannedPages.js` · `src/pages/ComingSoonPage.jsx` ·
`src/pages/NotFoundPage.jsx`

### How it works
`plannedPages.js` lists later-phase pages with their phase, capability and endpoints. `routes.jsx`
maps each one to `ComingSoonPage`. When you build, say, Explore in Phase 4, delete its entry and add
a real route. Nothing else changes.

### How to verify
Open a processed dataset: the sidebar shows its pages with phase tags (P4, P5…). Upload a file
without customer IDs: "Customers" shows **n/a** with a tooltip saying what's missing.

### What to learn
Client-side routing (the History API: the page never reloads); route params; nested routes and
outlets; layout components; single source of truth.

---

## 8. UI components (`src/components/ui/`)

### What we are building
Small building blocks (`Button`, `Card`, `Alert`, `Badge`, `StatusPill`, `TextField`, `Spinner`,
`EmptyState`, `ErrorState`, `StatTile`) used by every page.

### Why this way
Consistency, and accessibility done once: `TextField` links label, hint and error with
`htmlFor` / `aria-describedby`; `Alert` uses `role="alert"` for errors; `Spinner` has a
screen-reader label; `StatusPill` shows status as text **and** colour (never colour alone).

### How it works
Props with defaults plus `...rest` passthrough:
```jsx
export function Button({ variant = 'primary', size = 'md', loading = false, type = 'button', ...rest }) {
  return <button type={type} disabled={disabled || loading} className={buttonClasses({ variant, size })} {...rest}>
```
`type="button"` by default prevents the classic bug where any button inside a form submits it.
Links that *look* like buttons use `buttonClasses()` on a `<Link>`, because navigation must stay an
`<a>` element for accessibility.

### What to learn
Component composition; props and default values; the `children` prop; spreading props; semantic
HTML and ARIA roles.

---

## 9. The upload wizard

### What we are building
Steps 2–5 of the user journey: upload → review detected columns → confirm mapping → process →
report.

### Why this way
- **Two-step upload (ADR-05).** The server profiles the file first, and *you* confirm the mapping.
  Nothing is cleaned until you agree how columns are read.
- **Each step is its own component with its own state.** `UploadWizardPage` only decides which step
  to show and passes data between them. No file has to understand the whole flow.
- **Derived state, not duplicated state.** In `MapColumnsStep`, only `mapping` and the chosen date
  format are state. The capability preview, the list of problems and the enabled/disabled submit
  button are *calculated* from them on every render, so they can never disagree.

### Files
`src/pages/UploadWizardPage.jsx` · `src/components/upload/{ChooseFileStep, FileDropzone,
FieldGuidePanel, MapColumnsStep, ColumnMappingTable, DateFormatPicker, CapabilityList, WarningList,
ProcessingStep, UploadSteps}.jsx` · `src/utils/{fileValidation, capabilities, dates, csv}.js`

### How it works
1. **Choose.** `FileDropzone` validates on the client (extension, size, empty) for instant
   feedback; the server validates again. The **synthetic** checkbox labels invented data
   everywhere it appears (brief §33).
2. **Map.** `ColumnMappingTable` is *controlled*: it holds no state and reports every change with
   `onChange(field, column)`. A column used by one field is disabled in the others. If dates fit
   both day/month and month/day, `DateFormatPicker` requires a choice before you can continue.
3. **Process.** The server answers **202 Accepted**; `ProcessingStep` polls `GET /datasets/{id}`
   until `ready` (→ go to the report) or `failed` (→ show the reason and offer "Back to column
   mapping").
4. `?dataset=<id>` reopens the mapping step from the Datasets list ("Continue" or "Fix mapping").

**Capabilities are data, not code.** The field guide from the server includes rules like:
```json
{ "key": "segmentation", "requires_all": ["customer_id", "invoice_id", "occurred_at"],
  "requires_one_of": [["revenue"], ["quantity", "unit_price"]] }
```
`utils/capabilities.js` only *evaluates* them. If the backend changes a rule, the frontend
follows without a code change.

### How to verify
`ColumnMappingTable.test.jsx`, `FileDropzone.test.jsx`, `capabilities.test.js`, `dates.test.js`,
`csv.test.js`. Manually: upload a file with dates like `01/02/2024`: the date picker appears and
**Confirm** stays disabled until you choose.

### What to learn
Controlled vs uncontrolled inputs; lifting state up; derived state; `key` to reset a component
(`<MapColumnsStep key={dataset.id}>`); `FormData` and multipart uploads; `Blob`/object URLs for
downloads; drag-and-drop events.

---

## 10. The data-quality report

### What we are building
Step 5 of the user journey: every change made to the file, in order, with counts, reasons and
examples.

### Why this way
The brief requires that nothing is changed silently. The **conservation check**
(`rows in file = kept + excluded`) is shown as a sentence, so a reader can check the pipeline's
honesty at a glance. `MethodCard` gives the standard seven-part explanation (what, why, input,
output, assumptions, limitations, interpretation) required by brief §23.

### Files
`src/pages/DataQualityPage.jsx` · `src/components/upload/QualityReport.jsx` ·
`src/components/explain/MethodCard.jsx` · `src/content/methodCards.js`

### What to learn
Presenting data provenance; `<details>`/`<summary>` for disclosure without JavaScript;
`tabular-nums` for aligned numbers; separating content (text in `content/`) from components.

---

## 11. Tests

| File | What it protects |
|---|---|
| `utils/format.test.js` | Number, percent, byte and date formatting, including the UTC date rule |
| `utils/csv.test.js` | Quoted commas, escaped quotes, CRLF, BOM, partial last line, row limits |
| `utils/dates.test.js` | dd/mm vs mm/dd, impossible dates rejected, ambiguity detection |
| `utils/capabilities.test.js` | Revenue can come from quantity × price; duplicate and missing fields |
| `utils/fileValidation.test.js` | Extension, Windows MIME type, empty file, size limit |
| `utils/validation.test.js` | Registration rules |
| `services/apiClient.test.js` | Error normalisation, auth header, session expiry, network errors |
| `services/mock/schemaDetection.test.js` | Online Retail II headers map correctly; mismatches and ambiguity flagged |
| `services/mock/mockProcessing.test.js` | Conservation invariant; reasons; returns and guests kept |
| `hooks/usePolling.test.jsx` | Stops when done, on unmount, and on error |
| `components/upload/ColumnMappingTable.test.jsx` | A column can't be mapped twice; changes reported |
| `components/upload/FileDropzone.test.jsx` | Valid CSV accepted; wrong type and oversized rejected |
| `pages/LoginPage.test.jsx` | Sign-in call, server error message, session-expired notice |

Component tests use React Testing Library, which finds elements the way a user would (by label,
role and text), not by CSS class. So a refactor that keeps behaviour doesn't break tests.

---

## 12. React concepts, shown in this code

| Concept | Plain explanation | Where to look |
|---|---|---|
| **Component** | A function that returns what to show (JSX) for its inputs. | Every `.jsx` file, e.g. `StatTile` |
| **JSX** | HTML-like syntax that compiles to `React.createElement` calls. `className` instead of `class`, `{expression}` for values. | Anywhere |
| **Props** | Inputs passed from parent to child. Read-only for the child. | `<StatusPill status={dataset.status} />` |
| **State** | Values a component remembers between renders; changing them re-renders it. | `useState` in `LoginPage` |
| **Rendering** | React calls your component, compares the result with the last one, and updates only what changed in the DOM. | — |
| **Immutable updates** | Replace state, don't mutate it, or React won't notice: `setMapping(prev => ({ ...prev, [field]: column }))`. | `MapColumnsStep` |
| **Event handling** | Pass functions as `onClick`, `onChange`, `onSubmit`. `event.preventDefault()` stops the browser's default action. | `LoginPage.handleSubmit` |
| **Controlled input** | The input's value comes from state; every keystroke calls a setter. | `TextField` usage |
| **Hooks** | Functions starting with `use` that add React features. Only call them at the top level of a component, never inside `if` or loops. | `hooks/` |
| **Effects** | Code that syncs with the outside world (network, timers) *after* rendering, with a cleanup function. | `useApi`, `usePolling` |
| **Context** | Share a value with a whole subtree without prop drilling. | `AuthProvider`, `DatasetProvider` |
| **Lists and keys** | Each item in a mapped list needs a stable `key` so React can track it. Use IDs, not array indexes, for dynamic lists. | `DatasetsPage` rows |
| **Conditional rendering** | `{error && <Alert/>}`, or a ternary chain for loading/error/empty/data states. | `DatasetsPage` |

---

## 13. Where the complexity really is

- **Effects and async state** (`useApi`, `usePolling`, `AuthProvider`) are the hardest code here.
  Before changing them, make sure you can explain: what runs when the component unmounts
  mid-request? What happens in StrictMode's double mount? Why is the token in a ref?
- **Auth state transitions**: the redirect after sign-in happens in `PublicOnlyRoute`, not the
  form. Adding a `navigate()` to the form would race with it.
- **The mock is not the pipeline.** It covers 9 of the 12 steps, on preview rows only. Don't cite
  its numbers anywhere.
- **Date handling**: dataset timestamps are shown in UTC (`{ utc: true }`) so a transaction at
  23:30 in the UK isn't displayed as the next day in New Zealand. Upload times are shown in your
  local time. Mixing the two up is a classic bug.

---

## 14. What was verified, and what you must run

In the build sandbox, the npm registry refused to install Vite, Vitest, React Router and the
testing libraries, so the standard toolchain could not run there. Instead:

- Every source file was syntax-checked and the whole app **bundled** with esbuild (all imports
  resolve).
- The **46 pure-logic tests** (`utils/`, `apiClient`, mock detection and processing) were run with
  a small Vitest-compatible harness. All pass, after fixing the stateful-predicate bug in §4.
- The **full user flow** was driven in Chromium against the mock API, with no console errors:
  redirect to login → wrong-password error → registration validation → register → empty state →
  synthetic upload → mapping → processing → quality report (conservation check passed) → planned
  page → datasets list → ambiguous-date file (submit blocked until a format is chosen) → reload
  keeps the session → sign out. Styling was approximated with Tailwind v3 for that run.
- **Not run in the sandbox:** the React component and hook tests (they need jsdom and Testing
  Library), ESLint, and a real Vite/Tailwind v4 build.

On your machine, please run and report back anything that fails:
```bash
npm install && npm run lint && npm run test:run && npm run build
```
The dependency versions are the latest I could confirm from mid-2025 with caret ranges (`^`), so
npm installs the newest compatible minor versions. If `npm install` reports a peer-dependency
conflict, send me the message.

---

## 15. Suggested commits

Commit as you understand each part, not all at once:

1. `chore(frontend): scaffold Vite + React + Tailwind v4 with ESLint and Vitest`
2. `feat(frontend): design tokens and dark mode`
3. `feat(frontend): API client with error normalisation and auth injection`
4. `feat(frontend): in-browser mock API following the v1 contract`
5. `feat(frontend): auth context, route guards, login and register pages`
6. `feat(frontend): app shell, routing and capability-aware navigation`
7. `feat(frontend): upload wizard with column mapping and date-format check`
8. `feat(frontend): data-quality report page`
9. `test(frontend): unit and component tests`

---

## 16. Contract notes for the backend (Phase 2–3)

The mock defines what the frontend expects. Build FastAPI to match, or change both together:

- `POST /auth/login`: form fields `username`, `password` → `{ access_token, token_type }`.
- `POST /datasets`: multipart with `file` **and** `is_synthetic` (`"true"`/`"false"`) → 201 with
  `profile: { detected_columns[], suggested_mapping, missing_required[], warnings[],
  capabilities_preview[], preview: { rows_examined, file_truncated } }`.
- `GET /datasets/{id}` includes `profile` while status is `awaiting_mapping` or `failed` (so the
  mapping can be fixed and retried).
- `GET /datasets/field-guide` returns `{ fields[], capabilities[] }` with `requires_all` /
  `requires_one_of` rules; one capability is marked `required: true`.
- `GET /datasets` returns `{ items, total }`.
- Quality report fields: `summary`, `conservation`, `excluded_by_reason`, `actions[]` (`step`,
  `title`, `kind`, `rows_affected`, `rationale`, `examples`), `warnings`, `date_range`,
  `capabilities`, `pipeline_version`.

**Small updates to the architecture document these imply:** `is_synthetic` as an upload form
field; capability rules in the field guide; `quantity` marked *recommended* (it is required only for
demand forecasting, as the §12.1 footnote says); a `useDatasets` hook; `PageHeader` under
`components/layout/`.
