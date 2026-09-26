# Implementation Plan: GridLock

## Overview

This plan builds GridLock incrementally toward a demoable MVP loop first —
**upload → extract → review → map/timeline → tune thresholds → why-flagged → brief** —
then layers on stretch items (CSV/PDF export, 3+ utility scaling, AWS Lightsail + GoDaddy
deployment, transmission-line geometry).

The stack is fixed by the design: **Python 3.11 + FastAPI** backend, **React + Vite (TypeScript)**
frontend, **Postgres + PostGIS** data store, and **Gemini** for extraction
and brief generation. Property-based tests (Hypothesis for Python, fast-check for TS) implement the
18 correctness properties from the design; a golden-set accuracy harness and endpoint/integration
tests cover what PBT cannot.

The tasks are organized so a team of three can parallelize along the seams in the design:
- **Track A — Data / Extraction:** DB schema + PostGIS, DTOs, ingestion, Gemini extraction, geocoding, storage.
- **Track B — Matching / API / Deploy:** overlap SQL + scoring, brief generation, review/edit, error handling, export, deploy.
- **Track C — Frontend:** Vite scaffold, map, timeline, review table, sliders, why-flagged, source links, API wiring.

See the **Task Dependency Graph** at the end for the concrete parallel waves.

Tasks marked `*` are optional (tests) and can be skipped for a faster MVP but should be run before the demo.
Tasks and sub-tasks tagged **[Stretch]** are explicitly out of the MVP path.

## Tasks

- [x] 1. Backend scaffolding and shared foundations
  - [x] 1.1 Scaffold the FastAPI project and dev tooling
    - Create the backend package layout (`app/` with `api/`, `services/`, `models/`, `db/`, `core/`), `pyproject.toml`/`requirements.txt`, and an app entrypoint that runs under `uvicorn`
    - Add FastAPI app factory, health route, CORS for the Vite dev origin, and settings loaded from env (`DATABASE_URL`, `GEMINI_API_KEY`)
    - Configure Hypothesis + pytest and a `conftest.py`; add Ruff/format config
    - _Requirements: 1.1_

  - [x] 1.2 Define the shared error model and exception-to-HTTP mapping
    - Implement the consistent error JSON shape `{ "error": { "code", "message", "field?", "detected_format?" } }` and a FastAPI exception handler mapping domain exceptions to statuses (415, 413, 422, 404, 502, 504)
    - Define domain exceptions: `UnsupportedFormatError`, `FileTooLargeError`, `CorruptFileError`, `MissingMetadataError`, `PairNotFoundError`, `BriefTimeoutError`, `BriefGenerationError`, `ProjectNotFoundError`, `InvalidFieldError`, `InvalidParameterError`
    - _Requirements: 1.3, 1.4, 1.6, 1.7, 6.7, 8.5, 8.6, 8.7, 13.5, 13.6_

  - [x] 1.3 Define enums and the PartialDate model
    - Implement `ProjectType` enum (`substation | transmission line | generation`) and the `PartialDate { year, quarter?, month?, day? }` type with a `materialize()` that maps precision to a canonical `[start_date, end_date]` calendar span (e.g. Q2 2026 → 2026-04-01..2026-06-30) without refining precision
    - _Requirements: 2.4, 4.6_

  - [x]* 1.4 Write property test for PartialDate precision preservation
    - **Property 10: Date precision is preserved, never refined**
    - **Validates: Requirements 4.6**

- [x] 2. Data store: schema, PostGIS, and storage layer
  - [x] 2.1 Create the projects schema and PostGIS setup
    - Add a migration/DDL that enables the PostGIS extension and creates the `projects` table with `geom geography(Point, 4326)`, `start_date`/`end_date`, `confidence`, `reviewed`, `approximate`, provenance columns, plus the GIST index on `geom` and the `(start_date, end_date)` index
    - Provide a script/fixture to spin up a disposable Postgres+PostGIS test database (Docker container or scratch Tiger Data schema)
    - _Requirements: 5.1, 5.2, 5.3_

  - [x] 2.2 Implement the storage layer (persist, list, read-by-id, update)
    - Implement parameterized DB access (asyncpg or SQLAlchemy Core + GeoAlchemy2) to insert a Project, read one by id, list all, and update fields; convert `geom` ↔ lat/lng on write/read; round `voltage_kv` to nearest kV on persist
    - _Requirements: 5.1, 5.2, 5.4, 13.2_

  - [x]* 2.3 Write property test for persistence round-trip
    - **Property 13: Persistence round-trip** (runs against the disposable Postgres+PostGIS test DB)
    - **Validates: Requirements 5.1, 5.2, 5.3**

- [x] 3. API DTOs and the projects read/edit endpoints
  - [x] 3.1 Implement Pydantic DTOs
    - Implement `ProjectDTO`, `ScoreFactorsDTO`, `CoordinationPairDTO`, `CoordinationBriefDTO`, `IngestResult`, and the request/response models for `PATCH /projects/{id}`, including validators for field ranges (`confidence` 0..1, `voltage_kv` 0.1..2000, `type` enum-or-empty, `source_page` ≥ 1)
    - _Requirements: 2.4, 2.6, 3.1, 5.1_

  - [x] 3.2 Implement GET /projects
    - Wire the storage list to `GET /projects` returning `ProjectDTO`s (lat/lng from geom, null when unset)
    - _Requirements: 5.4_

  - [x] 3.3 Implement PATCH /projects/{id} (review and edit)
    - Validate incoming fields; on success persist edits and return the updated `ProjectDTO` within the 2s budget; support setting `reviewed = true`; reject invalid values with per-field 422 and persist nothing; return 404 for unknown ids
    - When an edit changes `geom`/dates, immediately re-run overlap matching for the affected project and update or invalidate that project's existing Coordination_Pairs (synchronous recompute for the hackathon); edited values also govern subsequent `GET /overlaps` queries
    - _Requirements: 13.2, 13.3, 13.4, 13.5, 13.6_

  - [x]* 3.4 Write property test for edit round-trip and effect on matching
    - **Property 14: Edit round-trip and effect on matching** (DB-backed): after a `geom`/date edit, the affected project's stale Coordination_Pairs are updated/invalidated and re-match is consistent with the post-edit values
    - **Validates: Requirements 13.2, 13.4**

  - [x]* 3.5 Write property test for rejected invalid edits leaving the target unchanged
    - **Property 15: Invalid edits are rejected and leave the target unchanged**
    - **Validates: Requirements 13.5**

- [x] 4. Ingestion service and endpoint
  - [x] 4.1 Implement synchronous ingestion validation
    - Implement `IngestionService.validate`: detect format from content (not just extension) accepting only PDF/XLSX/CSV, reject unsupported format naming the detected format, reject files > 50 MB, reject corrupt-but-supported files, require `utility` and `source_url` naming the missing field; perform no persistence on any rejection
    - _Requirements: 1.1, 1.3, 1.4, 1.6, 1.7_

  - [x] 4.2 Implement POST /ingest with async processing handoff
    - Accept multipart (`file` + `utility` + `source_url`), validate synchronously, assign a `plan_id`, record the plan with utility/source_url, return `202 { plan_id, status: "processing" }`, and schedule extraction via FastAPI `BackgroundTasks`; support a dataset of 2–50 distinct utilities
    - _Requirements: 1.1, 1.2, 1.5_

  - [x] 4.3 Implement document parsing (PDF/XLSX/CSV → page-annotated text)
    - Parse each supported format into page-annotated text/rows (pypdf/pdfplumber, openpyxl, csv) so extraction can attribute `source_page`; surface parse failures as `CorruptFileError`
    - _Requirements: 1.6, 2.7_

  - [x]* 4.4 Write property test for the ingestion accept/reject invariant
    - **Property 16: Ingestion accept/reject invariant**
    - **Validates: Requirements 1.2, 1.3, 1.4, 1.7**

  - [x]* 4.5 Write unit tests for corrupt-file and utility-count boundaries
    - Corrupt files per supported format (1.6); 2 / 50 / 51-utility boundaries (1.5)
    - _Requirements: 1.5, 1.6_

- [x] 5. Gemini structured extraction
  - [x] 5.1 Implement the extraction normalizer and record invariants
    - Implement the pure normalizer that turns raw model output into `ExtractedProject` records: clamp/validate `confidence` to [0,1], enforce `source_page` in [1, page_count], truncate `raw_excerpt` to 2000 chars, coerce `type` to the enum or empty, record `voltage_kv` only when within 0.1–2000 else empty, set undeterminable fields to empty while still creating the record, and default `reviewed = false`
    - _Requirements: 2.2, 2.3, 2.5, 2.6, 2.7, 2.8, 3.1, 3.2_

  - [x] 5.2 Implement the Gemini structured-extraction call
    - Implement `ExtractionService.extract`: build the schema-constrained (JSON output) request mirroring `ExtractedProject`, feed page-annotated document text, blend model self-reported certainty with a completeness heuristic for confidence, and on whole-document model failure create zero records and raise `ExtractionFailedError`
    - _Requirements: 2.1, 2.9, 3.1_

  - [x]* 5.3 Write property test for accepted extracted record schema invariants
    - **Property 11: Accepted extracted record satisfies schema invariants** (feed generated model-output into the normalizer; no live Gemini call)
    - **Validates: Requirements 2.4, 2.6, 2.7, 2.8, 3.1**

  - [x]* 5.4 Write property test for undeterminable fields emptied, record still created
    - **Property 12: Undeterminable fields are emptied, record still created**
    - **Validates: Requirements 2.3, 2.5**

  - [x]* 5.5 Write integration test for whole-document extraction failure
    - Mock Gemini to raise; assert zero persisted records and a surfaced failure
    - _Requirements: 2.9_

- [x] 6. Geocoding service
  - [x] 6.1 Implement the county-centroid gazetteer and Geocoder interface
    - Bundle a county-centroid gazetteer for deterministic offline fallback; define the pluggable `Geocoder` protocol and a hosted-geocoder adapter behind it
    - _Requirements: 4.2_

  - [x] 6.2 Implement geocoding resolution with timeout, retry, fallback, and ambiguity rules
    - Implement `GeocodingService.geocode`: single-candidate name → 4326 point; county reference → county centroid marked `approximate=true`; 10s per-attempt timeout with up to 3 attempts; all-fail → `requires_review` with geom unset; more-than-one candidate → treat as unresolved, `requires_review`, geom unset
    - _Requirements: 4.1, 4.2, 4.3, 4.4, 4.5_

  - [x] 6.3 Wire extraction → geocoding → persistence pipeline
    - In the background worker, for each extracted project call geocoding, apply the outcome (geom / approximate / requires_review), materialize PartialDate bounds, and persist via the storage layer
    - _Requirements: 2.1, 4.1, 4.2, 4.4, 5.1_

  - [x]* 6.4 Write property test for the geocoding resolution outcome
    - **Property 9: Geocoding resolution outcome** (mock the `Geocoder` and clock)
    - **Validates: Requirements 4.3, 4.4, 4.5**

  - [x]* 6.5 Write integration tests for geocoding examples
    - Mocked single-candidate → 4326 point with `approximate=false`; county reference → centroid with `approximate=true`
    - _Requirements: 4.1, 4.2_

- [x] 7. Matching engine: candidate query and scoring
  - [x] 7.1 Implement the parameterized PostGIS candidate query
    - Implement the `ST_DWithin`/`ST_Distance` + `daterange` overlap query with the `a.utility < b.utility` predicate (different utilities, no self-pairs, each unordered pair once), non-null geom filter, `:radius_m` (miles→meters) and `:pad` parameters, returning distance in miles and overlap days
    - _Requirements: 6.1, 6.2, 6.3, 6.4, 6.8, 6.9, 6.10_

  - [x] 7.2 Implement the four scoring functions and composite
    - Pure Python: `distance_score` (1.0 at 0, →0 at/beyond radius, monotone non-increasing), `overlap_score` (0 when ≤0 days, →1 at/beyond max_overlap, monotone non-decreasing), `type_similarity` (1.0 equal else 0.0), `voltage_similarity` (1.0 equal, decreasing in |Δ|, symmetric), and the convex-combination composite (weights ≥0 summing to 1); missing/invalid inputs → factor 0.0 and name added to `indeterminate_factors`
    - _Requirements: 7.1, 7.2, 7.3, 7.4, 7.5, 7.6, 7.7_

  - [x] 7.3 Implement GET /overlaps with parameter handling
    - Implement `MatchingEngine.overlaps`; wire `GET /overlaps?radius=&pad=` with defaults 25 mi / 30 days, reject negative or non-numeric `radius`/`pad` with a 422 naming the invalid parameter, run the candidate query, score each pair, and return `CoordinationPairDTO`s with per-factor and composite scores and a stable pair id (`a_id-b_id`, a_id<b_id)
    - _Requirements: 6.1, 6.5, 6.6, 6.7, 7.7_

  - [x]* 7.4 Write property test for valid pair membership
    - **Property 1: Valid pair membership** (DB-backed against Postgres+PostGIS)
    - **Validates: Requirements 6.2, 6.3, 6.4, 6.8, 6.10**

  - [x]* 7.5 Write property test for matching symmetry and well-formed distance
    - **Property 2: Matching symmetry and well-formed distance** (DB-backed)
    - **Validates: Requirements 6.1, 6.2, 6.9**

  - [x]* 7.6 Write property test for the distance score
    - **Property 3: Distance score is bounded and monotonically non-increasing**
    - **Validates: Requirements 7.1**

  - [x]* 7.7 Write property test for the overlap score
    - **Property 4: Overlap score is bounded and monotonically non-decreasing**
    - **Validates: Requirements 7.2**

  - [x]* 7.8 Write property test for type-similarity
    - **Property 5: Type-similarity is exact and symmetric**
    - **Validates: Requirements 7.3**

  - [x]* 7.9 Write property test for voltage-similarity
    - **Property 6: Voltage-similarity is bounded, monotone in difference, and symmetric**
    - **Validates: Requirements 7.4**

  - [x]* 7.10 Write property test for the composite score
    - **Property 7: Composite score is bounded and factor-monotone**
    - **Validates: Requirements 7.5**

  - [x]* 7.11 Write property test for indeterminate factor handling
    - **Property 8: Missing factor inputs are zeroed and flagged indeterminate**
    - **Validates: Requirements 7.6**

- [x] 8. Checkpoint - backend matching path
  - Ensure all tests pass, ask the user if questions arise.

- [x] 9. Brief generation
  - [x] 9.1 Implement the Brief_Generator with a 30s budget
    - Implement `BriefGenerator.generate`: look up the pair (404/`PairNotFoundError` if missing), build a Gemini prompt injecting both project types, distance in miles, and the overlapping window plus a proposed opportunity, wrap the call in a 30s timeout (504 on timeout, no partial brief), constrain/validate output to 1–4 sentences and ≤600 chars, and on other failure return an identifying error leaving the pair unchanged
    - _Requirements: 8.1, 8.2, 8.3, 8.4, 8.5, 8.6, 8.7_

  - [x] 9.2 Implement POST /overlaps/{id}/brief
    - Wire the endpoint to resolve the pair id, call the generator, return `CoordinationBriefDTO` on success and the mapped error responses (404/504/502)
    - _Requirements: 8.1, 8.5, 8.6, 8.7_

  - [x]* 9.3 Write integration tests for brief generation paths
    - Real pair produces a brief within 30s with injected facts present (8.3); mocked slow/failing client covers timeout/failure/not-found with no partial brief
    - _Requirements: 8.1, 8.3, 8.5, 8.6, 8.7_

- [ ] 10. Backend endpoint contract tests and unit examples
  - [x]* 10.1 Write endpoint contract tests (FastAPI TestClient)
    - `POST /ingest` accept/reject and no-partial-record (corrupt, oversize, bad format, missing metadata); `GET /projects`; `PATCH /projects/{id}` valid/invalid/not-found and 2s latency budget; `GET /overlaps` defaults and invalid-parameter rejection; `POST /overlaps/{id}/brief` errors
    - _Requirements: 1.3, 1.4, 1.6, 1.7, 5.4, 6.5, 6.6, 6.7, 8.5, 8.6, 8.7, 13.2, 13.5, 13.6_

  - [x]* 10.2 Write unit/example tests for config defaults and creation flags
    - `reviewed=false` on creation (3.2); config defaults 25 mi / 30 days (6.5, 6.6); `PATCH reviewed=true` (13.3); not-found ids (8.5, 13.6)
    - _Requirements: 3.2, 6.5, 6.6, 13.3_

  - [ ]* 10.3 Build the golden-set extraction accuracy harness
    - Assemble a small hand-labeled corpus (a few PDFs, an XLSX, a CSV) with expected Project records; run extraction and report project precision/recall and per-field accuracy plus source_page/raw_excerpt correctness; gate at a threshold (e.g. ≥80% field accuracy)
    - _Requirements: 2.1, 2.2, 2.7, 2.8_

- [x] 11. Frontend scaffolding and API client
  - [x] 11.1 Scaffold the React + Vite (TypeScript) app
    - Create the Vite React+TS project, base layout with regions for map, timeline, review table, sliders, and why-flagged panel, dev proxy to the FastAPI backend, and configure fast-check + a test runner (Vitest + React Testing Library)
    - _Requirements: 9.1, 9.2_

  - [x] 11.2 Implement the typed API client and shared types
    - Implement fetch wrappers for `POST /ingest`, `GET /projects`, `PATCH /projects/{id}`, `GET /overlaps?radius=&pad=`, `POST /overlaps/{id}/brief`, mirroring the backend DTOs; implement the pure `reviewProbe` predicate (`confidence < threshold`) and the `sourceLink(source_url, source_page)` builder
    - _Requirements: 3.3, 5.4, 12.1, 13.1_

  - [x]* 11.3 Write property test for the review predicate
    - **Property 17: Review predicate matches the threshold boundary** (fast-check)
    - **Validates: Requirements 3.3, 13.1**

  - [x]* 11.4 Write property test for the source-link builder
    - **Property 18: Source link encodes the page** (fast-check)
    - **Validates: Requirements 12.1**

- [x] 12. Frontend views and wiring
  - [x] 12.1 Implement the Leaflet map
    - Render one marker per project at its geom (skip unset geom), highlight projects that belong to a Coordination_Pair, and visually distinguish Approximate_Location markers (e.g. hollow/hatched)
    - _Requirements: 9.1, 9.3, 9.4_

  - [x] 12.2 Implement the timeline
    - Use vis-timeline to position each project by start/end date honoring quarter/year precision labeling
    - _Requirements: 9.2_

  - [x] 12.3 Implement the review table (Review_Screen) with inline edit
    - List projects, visually distinguish those below the Confidence_Threshold (default 0.7), and submit inline edits via `PATCH /projects/{id}` (including marking reviewed)
    - _Requirements: 3.3, 13.1, 13.2, 13.3_

  - [x] 12.4 Implement the threshold sliders with live re-query
    - Distance_Radius and Date_Padding sliders that re-query `GET /overlaps?radius=&pad=` on change and update the displayed pairs and map highlighting
    - _Requirements: 10.1, 10.2, 10.3, 10.4_

  - [x] 12.5 Implement the why-flagged panel
    - On selecting a pair, show the two projects side by side with distance, Overlap_Days, and each individual score factor; if a brief exists, display it; provide a control to request `POST /overlaps/{id}/brief`
    - _Requirements: 11.1, 11.2, 11.3_

  - [x] 12.6 Implement source-page links
    - Render each project's source link built from `source_url` + `source_page` and open the source document at that page on activation
    - _Requirements: 12.1, 12.2_

  - [x] 12.7 Wire the upload flow end to end
    - Add an upload control that posts to `POST /ingest`, surfaces the `plan_id`/processing status and validation errors, and refreshes projects once processing completes
    - _Requirements: 1.1, 1.2, 1.3, 1.4, 1.6, 1.7_

  - [x]* 12.8 Write UI component/interaction tests
    - Map markers with paired highlighting and approximate styling (9.1–9.4); timeline positioning (9.2); slider-driven re-query with new radius/pad (10.1–10.4); why-flagged side-by-side with factor breakdown and brief (11.1–11.3); review-table below-threshold styling (3.3, 13.1); source-link activation (12.2)
    - _Requirements: 3.3, 9.1, 9.2, 9.3, 9.4, 10.1, 10.2, 10.3, 10.4, 11.1, 11.2, 11.3, 12.2, 13.1_

- [x] 13. Checkpoint - MVP demo loop
  - Ensure all tests pass, ask the user if questions arise. Verify the full loop end to end: upload → extract → review → map/timeline → tune thresholds → why-flagged → brief.

- [ ] 14. [Stretch] Coordination brief export
  - [x] 14.1 Implement GET /export for CSV and PDF
    - Produce a CSV (stdlib `csv`) and a PDF (e.g. reportlab) of Coordination_Pairs and their briefs; validate that every record has both Projects' utilities and reject/block the export as invalid if any utility is missing; each record includes both utilities, both names, distance in miles, and the overlapping window
    - _Requirements: 14.1, 14.2, 14.3, 14.4_

  - [ ]* 14.2 Write property + example tests for export
    - Property: the export is rejected as invalid when any record is missing a utility (14.3); property: every exported CSV row contains both utilities, both names, miles, and the overlapping window (14.4); example/snapshot for the PDF
    - _Requirements: 14.1, 14.2, 14.3, 14.4_

- [x] 15. [Stretch] Additional utilities (3+)
  - [x] 15.1 Support ingesting and matching across 3+ utilities
    - Confirm ingestion accepts 3+ distinct utilities in one dataset and that the `a.utility < b.utility` predicate already evaluates every distinct utility combination; add any UI affordances for multiple utilities
    - _Requirements: 15.1, 15.2_

  - [x]* 15.2 Write property test for cross-utility coverage
    - With 3+ utilities, every distinct utility combination is considered by matching (DB-backed)
    - _Requirements: 15.2_

- [ ] 16. [Stretch] Transmission-line geometry
  - [ ] 16.1 Represent transmission lines by endpoint substations and match on line geometry
    - For `transmission line` projects, build a two-point/LINESTRING geometry from endpoint substations and measure distance for line-involving pairs against that geometry via the same `ST_Distance`/`ST_DWithin` operators
    - _Requirements: 17.1, 17.2_

  - [ ]* 16.2 Write example tests for line-involving distance
    - Line-involving distance uses the line geometry rather than a single point
    - _Requirements: 17.1, 17.2_

- [ ] 17. [Stretch] Public deployment (AWS Lightsail + GoDaddy)
  - [ ] 17.1 Configure the AWS Lightsail deployment
    - Build one container image serving the FastAPI backend under `/api` and the built React bundle at `/`; run it with Postgres/PostGIS and Caddy (HTTPS) via Docker Compose on one Lightsail instance, deployed over SSH from GitHub Actions only after tests pass on `master`; keep the DB password and `GEMINI_API_KEY` in GitHub secrets written to the server's `.env` so nothing sensitive is baked into the frontend bundle
    - _Requirements: 16.1_

  - [ ] 17.2 Configure the GoDaddy custom domain and TLS
    - Point the registered domain's DNS A record at the instance's static IP and set `SITE_ADDRESS` so Caddy provisions TLS so the Web_UI is reachable at the public domain over HTTPS
    - _Requirements: 16.2_

  - [ ]* 17.3 Write a deployment smoke test
    - Assert the public domain responds over HTTPS
    - _Requirements: 16.1, 16.2_

- [ ] 18. Final checkpoint - Ensure all tests pass
  - Ensure all tests pass (property, integration, endpoint, UI, and golden-set), ask the user if questions arise.

## Notes

- Tasks marked with `*` are optional (tests) and can be skipped for a faster MVP, but should be run before the demo.
- Tasks tagged **[Stretch]** (14–17) are out of the MVP path; build them only after the demo loop in tasks 1–13 works end to end.
- Each of Properties 1–18 is implemented by exactly one property-based test, tagged with a `# Feature: gridlock, Property {number}` comment and referencing the design property it validates.
- DB-backed properties (P1, P2, P13, P14) and cross-utility coverage run against a disposable Postgres+PostGIS test database so PostGIS behavior is exercised for real.
- Extraction accuracy is measured by the golden-set harness (task 10.3), not by property tests, since it depends on Gemini output quality.
- Checkpoints (tasks 8, 13, 18) ensure incremental validation; the task-13 checkpoint corresponds to a working MVP demo.
- Every task references the specific requirements (and, where applicable, the correctness property) it implements for traceability.

## Parallelization Guide

- **Track A — Data / Extraction:** tasks 1.3, 2.x, 4.x, 5.x, 6.x (schema, PartialDate, ingestion, extraction, geocoding, pipeline).
- **Track B — Matching / API / Deploy:** tasks 1.1, 1.2, 3.x, 7.x, 9.x, 10.x, and stretch 14/17 (scaffold, DTOs, projects endpoints, matching + scoring, briefs, contract tests, export, deploy).
- **Track C — Frontend:** tasks 11.x, 12.x (Vite scaffold, API client, map, timeline, review table, sliders, why-flagged, source links, upload wiring).

The dependency graph below sequences shared foundations (scaffold, DTOs, schema) into early waves so the three tracks can then proceed largely in parallel.

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1.1", "1.2", "1.3", "2.1", "11.1"] },
    { "id": 1, "tasks": ["1.4", "2.2", "3.1", "4.1", "4.3", "6.1", "11.2"] },
    { "id": 2, "tasks": ["2.3", "3.2", "3.3", "4.2", "5.1", "6.2", "7.1", "7.2", "11.3", "11.4"] },
    { "id": 3, "tasks": ["3.4", "3.5", "4.4", "4.5", "5.2", "5.3", "5.4", "6.4", "7.3", "7.6", "7.7", "7.8", "7.9", "7.10", "7.11", "12.1", "12.2", "12.3", "12.6"] },
    { "id": 4, "tasks": ["5.5", "6.3", "6.5", "7.4", "7.5", "9.1", "12.4", "12.7"] },
    { "id": 5, "tasks": ["9.2", "9.3", "12.5"] },
    { "id": 6, "tasks": ["10.1", "10.2", "10.3", "12.8"] },
    { "id": 7, "tasks": ["14.1", "15.1", "16.1", "17.1"] },
    { "id": 8, "tasks": ["14.2", "15.2", "16.2", "17.2"] },
    { "id": 9, "tasks": ["17.3"] }
  ]
}
```
