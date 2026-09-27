# GridMerge

Coordination radar for electric-utility capital planners. GridMerge ingests neighboring
utilities' capital plans (PDF / XLSX / CSV), extracts every project with Gemini, geocodes
and stores them in Postgres + PostGIS, flags cross-utility project pairs that are close in
space and time, scores them, and drafts a short coordination brief a planner can forward.

Spec: [`.kiro/specs/gridmerge`](.kiro/specs/gridmerge) (requirements, design, tasks).

```
backend/    FastAPI + asyncpg + PostGIS, Gemini extraction/briefs, Hypothesis tests
frontend/   React + Vite + TypeScript, Leaflet map, vis-timeline, Vitest + fast-check
sample_data/  generated demo plans for three fictional utilities (real towns/counties)
deploy/     Lightsail stack (app + PostGIS + Caddy), CI deploy script, instance bootstrap
source_docs/  public SC/GA/FL filings, their extracted citation CSVs, and the loaders' notes
```

Toolchain: Python 3.11+ (`backend/.python-version`), Node 22 (`.nvmrc`; Vite 8's
dependencies need ^22.22), Docker. `.gitattributes` pins line endings to LF so a Windows
checkout still builds working Linux containers.

## Quick start

```bash
# 1. Database (Postgres 16 + PostGIS)
docker compose up -d db

# 2. Backend (native Windows: .venv\Scripts\ instead of .venv/bin/)
cd backend
python3 -m venv .venv && .venv/bin/pip install -r requirements-dev.txt
cp .env.example .env            # set GEMINI_API_KEY to enable upload extraction + briefs
.venv/bin/python -m scripts.seed_demo   # optional: sample files + 19 demo projects
#   --region fl-ga: 24 ILLUSTRATIVE projects for real FL/GA utilities on the HIFLD lines
#   (placeholders, not from filings); --region all loads both sets
.venv/bin/uvicorn app.main:app --reload --port 8000

# 3. Frontend (proxies /api -> localhost:8000)
cd frontend
npm install
npm run dev                     # http://localhost:5173
```

Without `GEMINI_API_KEY` everything works except PDF extraction: uploads fail with
"Extraction failed: GEMINI_API_KEY is not configured" (the plan is marked failed, no
projects are created). Coordination briefs fall back to a template built from the pair's
facts (distance, timing, what the tier lets them share, rough value), stored and labelled
`template`. Ask GridMerge returns a 503 (the search bar itself never needs the key). The
seed script and the committed public-source snapshots load without it, so
the rest of the demo loop works offline.

### Demo walkthrough (Sperry Gridlock challenge)

1. The app opens on the **Southeast**: Dominion Energy South Carolina, Georgia Power and
   their neighbours in SC and GA, plus Florida's utilities. A green banner states what makes
   a match: **future work only** (in service from today), **within 40 km**, and **building
   at the same time** for at least 30 days. Every card shows the shared build time ("7
   months building together", "Both building Jun 2026 – Dec 2026"). The list is ranked by
   Sperry's tiers (touching → under 1.6 km → under 8 km → under 40 km), then by score.
2. Sperry's six reference overlaps (`source_docs/sperry_reference_overlaps.xlsx`) are all
   found within range (`tests/test_desc_gpc.py`), but none is a match any more. Every one
   involves a DESC project already in service (DESC's public list is a 2024–2028 budget; all
   five reference projects were due by 2025) or build windows years apart (Hooks – Thurmond
   2024 vs Evans – Thurmond 2033). "Only Dominion SC ↔ Georgia Power" in the utility menu
   shows that today no future DESC and Georgia Power work overlaps in time.
3. Current matches include:
   - DESC's Williams – Summerville 230 kV upgrade ($19.3M, May 2027) and the Pinopolis BESS
     (300 MW, Sep 2027): 27.7 km apart, both building Sep 2026 – May 2027.
   - Duke Energy Florida's Bartow BESS line and Tampa Electric's South Shore – Manatee
     230 kV line: both in service Dec 2027.
   - FPL solar sites and PowerSouth's Panhandle 115 kV lines.
4. Open a pair to see why it was flagged: the closest-point connector on the map, both
   build windows on one time axis (shared stretch hatched), the rough coordination value
   (Sperry bonus), side-by-side projects with source-page links, and a forwardable brief.
5. Export CSV/PDF downloads the pairs on screen (utility focus and distance bands).

### Whole stack in Docker (any OS)

The production stack runs the same way on Windows, macOS and Linux. Build the single image
(API at `/api`, React app at `/`) and start `deploy/docker-compose.yml` with a local `.env`:

```bash
docker build -f backend/Dockerfile -t gridmerge:local .
cp deploy/.env.example deploy/.env      # APP_TAG=local, a POSTGRES_PASSWORD, your key
docker compose -p gridmerge-local -f deploy/docker-compose.yml --env-file deploy/.env up -d
# http://localhost:8080   (HTTP_PORT in deploy/.env)
docker compose -p gridmerge-local -f deploy/docker-compose.yml --env-file deploy/.env   exec app python -m scripts.seed_demo --region fl-ga --db-only   # demo data
```

`-p gridmerge-local` keeps it apart from the dev `db`/`testdb` containers.

### Configuration (`backend/.env`)

| Variable | Default | Notes |
| --- | --- | --- |
| `DATABASE_URL` | `postgresql://gridmerge:gridmerge@localhost:5432/gridmerge` | Set by `deploy/docker-compose.yml` in prod |
| `GEMINI_API_KEY` | — | Extraction, briefs, Ask GridMerge |
| `GEMINI_MODEL` | `gemini-3.8-flash` | `gemini-2.5-flash` is closed to new keys |
| `GEMINI_RPM` | `5` | requests/minute across the app (free tier: 5); `0` = unpaced |
| `GEOCODER` | `nominatim` | `none` = offline county gazetteer only |
| `CORS_ORIGINS` | `http://localhost:5173` | comma-separated |
| `HIFLD_LINES_URL` | HIFLD ArcGIS FeatureServer layer | only used by `load_hifld --fetch` |
| `HIFLD_BBOX` | `-86.0,29.8,-80.8,31.6` | FL–GA region fetched by `load_hifld --fetch` |
| `AUTOLOAD_LINES` | `true` | load the committed snapshot into an empty table on startup |
| `PLANNING_FROM` | today | matches need both projects in service on or after this date; earlier work is finished and left out (`/projects?include_past=true` still lists it) |
| `MIN_OVERLAP_DAYS` | `30` | matches need both projects building at the same time for at least this many days |
| `COMPRESS_RESPONSES` | `true` | gzip API responses; the deploy stack sets `false` because Caddy compresses (zstd) |
| `SEARCH_ZIP_RADIUS_MILES` | `25` | a ZIP search matches projects this close to the ZIP (widens to 50, then 100, when empty) |
| `AUTH_USERNAME`, `AUTH_PASSWORD` | — | the one sign-in account; both set = sign-in required, either empty = open app |
| `AUTH_SECRET` | random per process | signs session cookies; set it so restarts and redeploys keep people signed in |
| `AUTH_SESSION_HOURS` | `12` | how long a sign-in lasts |

### Sign-in

With `AUTH_USERNAME` and `AUTH_PASSWORD` set, the app opens on a sign-in screen and every
API route (and `/samples`) returns `401 unauthenticated` without a session; `/health` and
`/auth/*` stay public. Signing in sets an HttpOnly, SameSite=Lax cookie (Secure over
HTTPS) holding an HMAC-signed expiry. Five failed sign-ins from one address lock it out for
15 minutes. In production the CI deploy writes the `AUTH_USERNAME`, `AUTH_PASSWORD`, and
`AUTH_SECRET` repository secrets into the server's `.env`; with them unset the site stays
open.

## API

| Method | Path | Purpose |
| --- | --- | --- |
| POST | `/auth/login` | `{"username", "password"}` → session cookie; `401 invalid_credentials`, `429 too_many_attempts` |
| POST | `/auth/logout` | clears the session cookie |
| GET | `/auth/session` | `{"required", "authenticated", "username"}` |
| POST | `/ingest` | multipart `file` + `utility` + `source_url` (+ optional `pages`, e.g. `27-102`) → `202 {plan_id}`; processing runs in the background |
| GET | `/plans`, `/plans/{id}` | ingestion status (`processing` / `complete` / `failed`) |
| GET | `/projects` | all stored projects |
| PATCH | `/projects/{id}` | review/edit; geom/date edits immediately re-match that project |
| GET | `/overlaps?radius=&bands=&utility=` | scored coordination pairs (default 25 mi; `bands` e.g. `touching,1.6,8,25,40`; repeat `utility` to keep only pairs between those utilities). Each pair has `link` (the closest points the distance measures) and `build_a`/`build_b` (each project's scored build window) |
| POST | `/overlaps/{id}/brief?radius=` | generate a brief (30 s budget; a facts-only `template` brief without a model) |
| GET | `/export?format=csv\|pdf&radius=&bands=&utility=` | briefs export (stretch) |
| GET | `/lines?bbox=&min_kv=&owner=` | existing transmission lines (HIFLD) as GeoJSON; `owner` may repeat |
| GET | `/lines/owners` | owner roster: line count, km, voltage range, raw HIFLD spellings |
| GET | `/search?q=&limit=` | search bar: ZIP code, state, company (name, acronym like `FPL`, or prefix), project type, and text, combined (`FPL 33101`, `Georgia transmission`). Deterministic Postgres + pg_trgm, no LLM |
| POST | `/ask` | `{"question"}` → Gemini answer grounded in GridMerge data: the model calls `search_gridmerge`, `get_project_details`, and `find_coordination_overlaps`, which run here against Postgres; cited projects come back as `[#id]` (90 s budget) |

Errors always look like `{"error": {"code", "message", "field?", "fields?", "detected_format?"}}`.

## Existing transmission lines (HIFLD)

The map draws existing transmission lines from HIFLD *Electric Power Transmission Lines*
(the dataset behind the Felt "US Electric Power Transmission Lines" map) beneath the
planned projects, colored by owner with the same color as that utility's projects. They
are a **reference layer only**, kept in their own `transmission_lines` table and never
matched as planned projects.

- **Snapshot, not a live dependency.** DHS retired the public HIFLD portal in 2025; the
  ArcGIS service still answers but may disappear. `backend/app/data/hifld_lines.geojson.gz`
  (857 lines, ~220 KB) is committed and loaded on startup, so the app, tests and
  deployments never call HIFLD. Refresh it, or change the region, with:

  ```bash
  cd backend
  .venv/bin/python -m scripts.load_hifld --fetch                       # uses HIFLD_BBOX
  .venv/bin/python -m scripts.load_hifld --fetch --bbox=-86,29.8,-80.8,31.6
  ```

  Mirror if the service goes away: Data Rescue Project, *HIFLD Open Transmission Lines*.
- **Owner names are normalized** in `app/services/owners.py` (`ALIASES`): Duke's
  `INC`/`LLC` spellings merge and Gulf Power folds into Florida Power & Light (merged
  2021). The raw HIFLD name stays in `owner`. Add aliases as new owners appear.
- **Gaps:** ~15% of lines in the FL–GA box have no published owner; co-ops and
  municipals (Seminole, Tallahassee, Talquin, MEAG, Oglethorpe) are thin or missing; most
  source dates are 2014-era. Planned projects still come from the utilities' filings
  (SERTP / Georgia Power IRP, Florida PSC Ten-Year Site Plans, FRCC) via `/ingest`.

## Real planned projects (source filings)

Planned projects come from public filings uploaded through `/ingest` (or the UI), with an
optional **page range** (`pages=27-102` / "Pages" box) so only the planned-transmission
section of a long filing is extracted. Page numbers stay those of the original PDF.
Multi-owner filings (SERTP, FRCC) keep each project's owner (`GTC:`, `MEAG:`, owner
columns), canonicalized in `app/services/owners.py` to the same names as HIFLD owners.
The FL–GA filing set, page ranges, and a one-shot upload script are in
[`source_docs/`](source_docs/README.md).

**Region: the Southeast (SC, GA) plus Florida** (`app/sources/region.py`). Six structured
sources load without Gemini (`cd backend && .venv/bin/python -m
scripts.load_public_sources all`):

- **Dominion Energy South Carolina**: SCRTP "Planned Transmission Projects $2M and above,
  2024-2028" (44 projects, with costs).
- **Georgia Power**: 2025 IRP Vol 3, Table 2 "Georgia ITS 10 Year Plan" (138 projects).
- **SERTP 2026 preliminary 10-year expansion plan**: the 189 of its 426 projects located in
  SC, GA or FL (Southern Company, Georgia Transmission Corp, MEAG, Dalton, Duke Energy
  Carolinas' SC work, ...).
- **Florida utilities**: FRCC 2026 Load and Resource Plan, Form 13 "Proposed Transmission
  Lines" (Duke Energy Florida, FPL, Tampa Electric, Lakeland, Seminole, PowerSouth; 23
  lines) and the City of Tallahassee 2026 Ten Year Site Plan, Table 4.2 (2 lines).
- **EIA-860M planned generators** (August 2026) in SC, GA and FL: 78 plant sites at EIA's
  published coordinates (`--states ALL` loads the nationwide list).

Substations are placed from a cached OpenStreetMap lookup, with county centres
(approximate) as fallback and `app/data/place_overrides.csv` for sourced corrections.
The raw originals of every source are committed in `source_docs/`, and each run writes a
per-project citation table (file, page/sheet, excerpt) to `source_docs/extracted/`.
Those CSVs ship in the Docker image, and on startup the app inserts any source whose
plan is missing or was loaded from a different version of its CSV (SHA-256 kept on the
plan), so the AWS Lightsail deploy gets all 474 projects with no manual step
(`AUTOLOAD_PUBLIC_SOURCES=false` turns it off). To refresh: re-run the loader, commit
the CSVs, deploy; the new snapshot replaces the old rows on startup (briefs on replaced
projects are dropped with them).
Matches are labelled *potential coordination opportunities*: SERTP's listed projects are
not a commitment to build.

Gemini free tier: 5 requests/minute and 20/day per model. The app paces all Gemini calls
to `GEMINI_RPM` (default 5) and fails fast with a clear message once the daily quota is
used up.

## Deploy to AWS Lightsail

Deploys are automatic: every push to `master` that passes CI ships to one Lightsail
instance (see [CI/CD](#cicd)). One-time instance setup:

1. Create an Ubuntu 24.04 instance with **2 GB RAM or more**, attach a static IP, and in
   *Networking* open TCP 22, 80 and 443.
2. On the instance, install Docker and add swap:
   `curl -fsSL https://raw.githubusercontent.com/noddle-Cake/gridlock/master/deploy/lightsail-setup.sh | bash`
3. Add the deploy public key to `~/.ssh/authorized_keys` and set the repo secrets listed
   under CI/CD. Optionally point a domain at the IP and set the `SITE_ADDRESS` variable.

Real planned projects are loaded after a deploy by uploading the filings in
[`source_docs/`](source_docs/README.md): `bash source_docs/ingest.sh https://<host>/api`.

## Tests

```bash
docker compose up -d testdb     # disposable PostGIS on :5433 (tmpfs)
cd backend && .venv/bin/pytest  # 216 tests; DB-backed ones skip if testdb is down
cd frontend && npm test         # 79 tests
```

All 18 design properties have a property-based test (Hypothesis / fast-check, ≥100 cases),
tagged `Feature: gridmerge, Property N`. P1, P2, P13, P14 run against real PostGIS.

## CI/CD

`.github/workflows/ci-cd.yml` runs on every PR and push to `master`:

- **backend** — `ruff` + full `pytest` against a PostGIS service container (fails if any
  DB-backed test is skipped)
- **frontend** — `oxlint`, `vitest`, `vite build`
- **deploy** — only on `master` and only if both pass: builds one image
  ([`backend/Dockerfile`](backend/Dockerfile): FastAPI at `/api` + the React build at `/`,
  entrypoint `app.serve:app`), copies it over SSH to a single AWS Lightsail instance, and
  restarts the [`deploy/`](deploy) Compose stack (app + Postgres/PostGIS + Caddy for HTTPS).
  If the new app never turns healthy the previous version is restored; then the public URL
  is smoke-tested.

Repo secrets: `DEPLOY_HOST` (instance static IP), `DEPLOY_SSH_KEY` (private key whose public
half is in the instance's `authorized_keys`), `POSTGRES_PASSWORD` (URL-safe; only applied
when the DB volume is first created), `GEMINI_API_KEY`. Optional repo variable
`SITE_ADDRESS` (e.g. `3-90-12-34.sslip.io` or a real domain pointed at the IP) turns on
automatic HTTPS; without it the site is plain HTTP on the IP. The database lives in the
`gridlock_pgdata` Docker volume on the instance — enable Lightsail automatic snapshots for
backups.

## Coordination value estimate (Sperry bonus)

Every flagged pair carries a rough, assumption-based `impact` (`app/services/impact.py`),
shown under "Rough coordination value" in the pair panel and exported as `value_*_usd`
columns. Each distance tier unlocks one more kind of sharing, and nearer tiers keep the
farther tiers' benefits:

| Tier | Adds | Assumed value |
| --- | --- | --- |
| under 40 km | one crew/equipment mobilization instead of two | 1–3% of the smaller published project cost (DESC publishes costs), else $150k–$400k |
| under 8 km | one laydown yard, shared deliveries | $100k–$300k |
| under 1.6 km | access roads and permits; right-of-way land where both are routed lines | $50k–$200k; shared corridor km × half the narrower ROW width (23–61 m by kV) × $5k–$20k/acre |
| touching | one coordinated outage and crossing design | $50k–$250k |

Every match now builds at the same time, so crew, yard and outage sharing always count.
These figures are placeholders to start a conversation, not benchmarks: edit the constants
in `impact.py`.

Example: DESC's Williams – Summerville 230 kV upgrade ($19.3M, in service May 2027) and the
Pinopolis BESS (300 MW, Sep 2027) are 27.7 km apart and both building Sep 2026 – May 2027,
so the estimate is about $193k–$579k from one shared crew and equipment mobilization (1–3%
of DESC's published cost).

## Design notes and deviations

- **Review threshold boundary.** Requirements 3.3/13.1 say "equal to or below" the
  Confidence_Threshold; design Property 17 says `<`. The implementation follows the
  requirements (`confidence <= threshold`).
- **A match is close in space and time** (`matching.Rules`, `qualifies`). Geography
  selects the candidates (within 40 km), and timing is required as well:
  - both projects must still be ahead (in service on or after `PLANNING_FROM`, default
    today), because finished work has nothing left to coordinate;
  - both must be building at the same time for at least `MIN_OVERLAP_DAYS` (30).

  Pairs years apart or undated are not matches. This reverses PR #8, which flagged on
  distance alone so that Sperry's reference overlaps (time gaps 152–3,074 days, DESC
  projects due 2023–2025) would all appear. They are still found within range, but none is
  a match.
- **Timing is scored from each project's build window, with no date padding**
  (`app/services/timing.py`). A plan's start–end range is used as given; a project with
  only an in-service date is assumed to build for the 12 months before its in-service
  period (a year-only "2026" builds Jan 2025–Dec 2026). The time factor is
  `overlap_ratio` = days both are building ÷ days either is (intersection over union), so
  two "in service 2026" projects score 1.0 and no UI setting can inflate it. Each pair
  also reports `overlap_days` (the shared stretch, `window_start`–`window_end`) and
  `time_gap_days` (days between the in-service dates, as in Sperry's overlap table).
  Weights (`app/services/scoring.py`): distance 0.55, timing 0.30, type 0.075,
  voltage 0.075.
- **Overlap definition.** The challenge brief says "within 25 mi", the extended
  instructions "within 40 km (25 miles), measured between the projects' closest points",
  and the locations guide measures centre to centre. GridMerge measures closest points
  (a planned line counts from anywhere along it) out to 40 km, which can only be nearer
  than Sperry's centre-to-centre figures, and ranks by Sperry's four distance tiers.
- **Pair identity** is `"{a_id}-{b_id}"` with `a_id < b_id`, joined on
  `lower(trim(utility))` inequality, so "Met-Ed" and "met-ed " are the same utility.
- **Projects missing both dates** still match on distance; their timing factor is
  flagged indeterminate. One known date is used for both ends.
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
- Real routes for planned lines (stretch 16): a planned line whose two endpoints match
  exact OSM substations is stored as a straight `route` between them, and matching measures
  closest points between routes and points (a line crossing another is 0 km, "touching").
  Snapping those segments to the HIFLD corridor they rebuild is not done yet.
- Custom domain (stretch 17).
- Export property tests (14.2); only example tests exist.
