# Current collision audit — September 27, 2026

## Scope and results

The deployed GitHub revision was `f91a141` at `https://gridmerge.us`. Its API
requires sign-in. This audit covers that revision's committed snapshots and the
proposed update, **not the private live database or user uploads**. A read-only
live audit remains necessary when database access is available.

Radius: 40 km. Minimum shared estimated construction time remaining after the
cutoff: 30 days. Scheduled dates are forecasts, not proof of active construction.
Some locations are approximate; even exact endpoints are joined by straight lines,
not surveyed rights-of-way. These are coordination candidates for review.

| Measure | Before (deployed snapshots/rules) | Proposed update |
| --- | ---: | ---: |
| Project records | 474 | 484 |
| Current records | 400 | 430 |
| Archived records | 74 | 54 |
| Candidate matches | 572 | 523 |
| Direct Dominion SC ↔ Georgia Power matches | 0 | 8 |

[All company counts and decisions](current_company_audit.csv) are included.
Twenty-five names, covering 26 current records, require ownership review and
cannot generate matches. Unknown names in future uploads are also withheld.
Extraction review does not override ownership review.

The smaller match total reflects ownership exclusions and remaining-time checks.
More projects are current because the newer Dominion filing updates their dates.
Historical records remain available through `include_past=true`.

## Evidence and source changes

- Replace the 44-project DESC 2024–2028 loader edition with the
  [54-project 2026–2030 filing](https://www.scrtp.com/assets/pdfs/home/2026-2030-2million-and-above-project-descriptions.pdf).
  Startup retires only the exact old loader identity, atomically with insertion.
  User uploads remain intact; the old PDF/CSV remain available as historical references.
- The source prints April 31 and June 31. Retain month precision and disclose the
  invalid day in the excerpt; do not invent a day.
- [Ingka's September 23 announcement](https://www.ikea.com/us/en/newsroom/corporate-news/ingka-investments-brings-kingstree-west-solar-farm-into-operation-adding-new-renewable-electricity-in-south-carolina-pub9c17e940/)
  confirms Kingstree West operating, superseding its August EIA October forecast.
  A dated, exact-record override excludes it from current lists, search and matches
  while preserving the original planned dates and the new evidence citation.
- Other sources remain SERTP 2026, Georgia Power 2025 IRP, FRCC/Tallahassee 2026,
  and August 2026 EIA-860M. Completion or cancellation beyond the available evidence
  is not certified for every project.

See the [ownership policy](company_ownership.md) and
[evidence registry](../backend/app/data/company_ownership.csv).
FRP/FPL remain one NextEra family. Additional exclusions cover verified energyRe,
Silicon Ranch and Ingka subsidiaries. Placid Solar and Placid Solar II remain
unverified: a common investment manager does not establish common controlling
ownership. Pinopolis belongs to Aypa; its Santee Cooper PPA is not ownership.

## Reproduce and deploy

From `backend`, with a disposable PostGIS database running:

```bash
.venv/bin/python -m scripts.audit_collisions --snapshots --as-of 2026-09-27 > audit.json
.venv/bin/pytest -q
```

The snapshot audit uses `TEST_DATABASE_URL` and a uniquely named schema inside
a transaction that is rolled back. It does not rewrite existing tables.
For the deployed data, run inside the backend container with its existing
`DATABASE_URL`; this transaction is read-only:

```bash
python -m scripts.audit_collisions --live --as-of 2026-09-27 > live-audit.json
```

Deployment applies ownership checks on reads and loads the new DESC CSV at
startup. AWS needs neither Gemini nor a PDF download for this update. Compare
the live report, including uploads, against this baseline after deployment.
This report does not claim deployment has occurred.

Validation: 323 backend tests passed (including PostGIS), 99 frontend tests passed,
and the frontend production build succeeded.

## Dominion SC ↔ Georgia Power candidates

Pages refer to the new DESC PDF and Georgia Power's 2025 IRP Volume 3 in
[docket 56002](https://psc.ga.gov/search/facts-docket/?docketId=56002).
Dates below are remaining estimated shared build windows.

| DESC project (page) | Georgia Power project (page) | km | Remaining shared window | Approximate location |
| --- | --- | ---: | --- | --- |
| Jasper – Okatie 230 kV #2: Construct (12) | Goshen (Sav) - Mcintosh 115Kv Line Rebuild (183) | 4.9 | 2026-09-27–2026-12-01 | No |
| Okatie 230-115kV Substation, Jasper – Yemassee 230kV #1 Fold-in (11) | Goshen (Sav) - Mcintosh 115Kv Line Rebuild (183) | 13.61 | 2026-09-27–2026-12-31 | No |
| Jasper – Okatie 230 kV #2: Construct (12) | Goshen (Sav) - Kraft 115Kv Line Rebuild (183) | 14.78 | 2026-09-27–2026-12-01 | No |
| Okatie 230-115kV Substation, Jasper – Yemassee 230kV #1 Fold-in (11) | Goshen (Sav) - Kraft 115Kv Line Rebuild (183) | 19.15 | 2026-09-27–2026-12-31 | No |
| Okatie – McIntosh 115kV Tie: Add Series Reactor (41) | Coleman - Dean Forest 115Kv Line Rebuild (184) | 27.5 | 2027-12-31–2028-06-01 | No |
| Okatie – McIntosh 115kV Tie: Add Series Reactor (41) | Dean Forest - Little Ogeechee 230 Kv Rebuild (186) | 29.59 | 2028-06-01–2028-12-31 | No |
| Okatie – McIntosh 115kV Tie: Add Series Reactor (41) | Boulevard - Magnolia 115 Kv Line Rebuild (186) | 33.67 | 2028-06-01–2028-12-31 | No |
| Okatie – McIntosh 115kV Tie: Add Series Reactor (41) | Magnolia - Truman Parkway 115Kv Rebuild (184) | 34.83 | 2027-12-31–2028-06-01 | Yes |
