# GridLock

Coordination radar for electric-utility capital planners. GridLock ingests neighboring
utilities' capital plans (PDF / XLSX / CSV), extracts every project with Gemini, geocodes
and stores them in Postgres + PostGIS, flags cross-utility project pairs that are close in
space and time, scores them, and drafts a short coordination brief a planner can forward.

Spec: [`.kiro/specs/gridlock`](.kiro/specs/gridlock) (requirements, design, tasks).

```
backend/    FastAPI + asyncpg + PostGIS, Gemini extraction/briefs, Hypothesis tests
frontend/   React + Vite + TypeScript, Leaflet map, vis-timeline, Vitest + fast-check
sample_data/  generated demo plans for three fictional utilities (real towns/counties)
```

## Quick start

```bash
# 1. Database (Postgres 16 + PostGIS)
docker compose up -d db

# 2. Backend
cd backend
python3 -m venv .venv && .venv/bin/pip install -r requirements-dev.txt
cp .env.example .env            # set GEMINI_API_KEY to enable upload extraction + briefs
.venv/bin/python -m scripts.seed_demo   # optional: sample files + 19 demo projects
.venv/bin/uvicorn app.main:app --reload --port 8000

# 3. Frontend (proxies /api -> localhost:8000)
cd frontend
npm install
npm run dev                     # http://localhost:5173
```

Without `GEMINI_API_KEY` everything works except the two LLM steps: uploads fail with
"Extraction failed: GEMINI_API_KEY is not configured" (the plan is marked failed, no
projects are created), and brief generation returns a 502. The seed script loads
pre-extracted projects so the rest of the demo loop works offline.

### Configuration (`backend/.env`)

| Variable | Default | Notes |
| --- | --- | --- |
| `DATABASE_URL` | `postgresql://gridlock:gridlock@localhost:5432/gridlock` | Tiger Data connection string in prod |
| `GEMINI_API_KEY` | — | Extraction + briefs |
| `GEMINI_MODEL` | `gemini-2.5-flash` | |
| `GEOCODER` | `nominatim` | `none` = offline county gazetteer only |
| `CORS_ORIGINS` | `http://localhost:5173` | comma-separated |

## API

| Method | Path | Purpose |
| --- | --- | --- |
| POST | `/ingest` | multipart `file` + `utility` + `source_url` → `202 {plan_id}`; processing runs in the background |
| GET | `/plans`, `/plans/{id}` | ingestion status (`processing` / `complete` / `failed`) |
| GET | `/projects` | all stored projects |
| PATCH | `/projects/{id}` | review/edit; geom/date edits immediately re-match that project |
| GET | `/overlaps?radius=&pad=` | scored coordination pairs (defaults 25 mi / 30 days) |
| POST | `/overlaps/{id}/brief?radius=&pad=` | generate a brief (30 s budget) |
| GET | `/export?format=csv\|pdf` | briefs export (stretch) |

Errors always look like `{"error": {"code", "message", "field?", "fields?", "detected_format?"}}`.

## Tests

```bash
docker compose up -d testdb     # disposable PostGIS on :5433 (tmpfs)
cd backend && .venv/bin/pytest  # 65 tests; DB-backed ones skip if testdb is down
cd frontend && npm test         # 22 tests
```

All 18 design properties have a property-based test (Hypothesis / fast-check, ≥100 cases),
tagged `Feature: gridlock, Property N`. P1, P2, P13, P14 run against real PostGIS.

## CI/CD

`.github/workflows/ci-cd.yml` runs on every PR and push to `master`:

- **backend** — `ruff` + full `pytest` against a PostGIS service container (fails if any
  DB-backed test is skipped)
- **frontend** — `oxlint`, `vitest`, `vite build`
- **deploy** — only on `master` and only if both pass: builds one image
  ([`backend/Dockerfile`](backend/Dockerfile): FastAPI at `/api` + the React build at `/`,
  entrypoint `app.serve:app`), pushes it to the AWS Lightsail container service `gridlock`
  (us-east-1, created on first deploy), waits for the health check, then smoke-tests the URL.
  A deploy that fails its health check leaves the previous version live.

Required repo secrets: `AWS_ROLE_ARN` (IAM role GitHub Actions assumes via OIDC),
`DATABASE_URL` (Tiger Data / any Postgres with PostGIS available), `GEMINI_API_KEY`.

## Design notes and deviations

- **Review threshold boundary.** Requirements 3.3/13.1 say "equal to or below" the
  Confidence_Threshold; design Property 17 says `<`. The implementation follows the
  requirements (`confidence <= threshold`).
- **Overlap days** are the inclusive day count of the intersection of the two *padded*
  ranges (Req 6.10). The design's sample SQL padded only one side; both are padded here.
- **Pair identity** is `"{a_id}-{b_id}"` with `a_id < b_id`, joined on
  `lower(trim(utility))` inequality, so "Met-Ed" and "met-ed " are the same utility.
- **Projects missing both dates** can't be tested for temporal overlap and are excluded
  from matching (like projects with no geom). One known date is used for both ends.
- **Briefs** are the only persisted pair state. They record the thresholds they were
  generated under; a geom/date edit re-checks them — pairs that no longer qualify lose
  their brief, pairs that still qualify get refreshed facts and an "outdated" flag.
- **Geocoding.** County references use the bundled Census 2023 county gazetteer
  (offline, deterministic, marked approximate). Names go to Nominatim with a 10 s timeout
  and up to 3 attempts on errors/timeouts; zero or multiple candidates → requires review.
  Substations that don't resolve fall back to their town name, marked approximate.
- **Brief guarantees.** The brief is trimmed to ≤ 4 sentences / 600 chars; if the model
  omits the distance or window, a deterministic facts sentence is prepended.
- `voltage_kv` is an `int` column per the starter schema (34.5 kV is stored as 34/35).

## Not yet done

- Golden-set extraction accuracy harness (task 10.3) — needs a hand-labeled corpus.
- Transmission-line geometry (stretch 16) and the custom domain (stretch 17).
- Export property tests (14.2); only example tests exist.
