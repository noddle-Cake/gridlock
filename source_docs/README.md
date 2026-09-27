# Source documents

Every planned project GridMerge shows comes from one of the public files in this folder.
They are committed unchanged (the originals, as downloaded) so any record can be traced
back to the exact file and page it was read from, even if the publisher moves or replaces
the file. `extracted/` holds what was read out of them: one CSV row per project with its
source file, page/sheet and verbatim excerpt.

**Built entirely on public filings.** Nothing here comes from CEII / secure areas: SERTP
publishes this report as its Non-CEII version (its page headers still print "(CEII)"),
EIA-860M is a public federal dataset, and the Florida PSC posts the Ten-Year Site Plans
publicly. Substation positions come only from OpenStreetMap (already public) and are
rounded to ~100 m; anything that can't be placed from public data is shown at its county
centre and marked approximate, or left unplaced for review.

**Georgia Power's IRP page banner.** Table 2 of `georgia_power_2025_irp_vol3_public.pdf`
still prints the "CRITICAL ENERGY INFRASTRUCTURE INFORMATION - CONFIDENTIAL" banner of the
original, but the file is the *public disclosure* version Georgia Power filed with the
Georgia PSC, with the CEII content (the cost columns) redacted. Only the unredacted
fields are used: zone, TEAMS number, project name, need date and sponsor. Sperry Tech
supplied this file for the challenge, and its reference overlaps are drawn from this table.

**Plans are not commitments.** SERTP states its listed projects "do not represent a
commitment to build", and much of the Ten-Year Site Plan data is preliminary and given in
general terms. GridMerge labels matches as *potential coordination opportunities*.

## Files

| File | Source (retrieved 2026-09-26) | How it's loaded | Content |
| --- | --- | --- | --- |
| `eia860m_august_generator2026.xlsx` | [EIA-860M, August 2026](https://www.eia.gov/electricity/data/eia860m/xls/august_generator2026.xlsx) (newest edition that downloads; the Sep-Dec links on the EIA page return 503) | `load_public_sources eia860m` (no LLM) | "Planned" sheet: 2,312 generators planned but not yet operating, with plant lat/long and planned operation month. Default load is the region (SC, GA, FL): 86 generators at 78 plant / in-service-month sites (`--states ALL` loads the nationwide 1,649). Puerto Rico (`Planned_PR` sheet) is not loaded. |
| `sertp_2026_preliminary_expansion_plan.pdf` | [SERTP 2026 Preliminary Expansion Plan Report (Non-CEII)](https://www.southeasternrtp.com/docs/general/2026/2026_SERTP_Preliminary_Expansion_Plan_Report_(Non-CEII).pdf), dated 06/12/2026 | `load_public_sources sertp` (pdfplumber, no LLM) | 426 projects, in-service 2027-2036, by balancing area: AECI p1 (3), Duke Carolinas p2-16 (56), Duke Progress East p17-22 (17), Duke Progress West p23 (1), LG&E/KU p24-26 (10), Southern p27-102 (288: SOCO 204, GTC 67, MEAG 12, PowerSouth 4, Dalton 1), TVA p103-115 (51). The 189 located in SC, GA or FL are loaded (Southern Company 92, GTC 67, Duke Energy Carolinas 14, MEAG 12, ...). |
| `desc_2024-2028_projects_2m_and_above.pdf` | [DESC Planned Transmission Projects $2M and above, 2024-2028](https://www.scrtp.com/assets/pdfs/home/2024-2028-2million-and-above-project-descriptions.pdf) (SCRTP; also in the Sperry Tech challenge kit) | Archived reference; not loaded at startup | 44 Dominion Energy South Carolina projects, one per page: title, project ID, description, need, status, planned in-service date and estimated cost by year. |
| `desc_2026-2030_projects_2m_and_above.pdf` | [DESC 2026–2030 projects](https://www.scrtp.com/assets/pdfs/home/2026-2030-2million-and-above-project-descriptions.pdf) | `load_public_sources desc` (pdfplumber, no LLM) | 54 projects; supersedes the 2024–2028 loader edition. |
| `georgia_power_2025_irp_vol3_public.pdf` | Georgia Power 2025 IRP, Volume 3 (public disclosure), [Georgia PSC Docket #56002](https://psc.ga.gov/search/facts-docket/?docketId=56002); from the Sperry Tech challenge kit | `load_public_sources gpc` (pdfplumber, no LLM), pages 177-190 | Table 2 "Georgia ITS 10 Year Plan Project List": 208 rows. The 138 Georgia Power rows (sponsor GPC or SAV) are loaded; GTC/MEAG/DU rows are other utilities already listed in SERTP. |
| `sperry_reference_overlaps.xlsx` | Sperry Tech challenge kit (`Projects_Overlaps.xlsx`) | not loaded; used by `tests/test_desc_gpc.py` | Sperry's hand-built reference: 5 DESC + 5 Georgia Power projects and the 6 overlaps between them. The acceptance test requires all 6 to be found within range; none is a current match (each involves DESC work due by 2025 or build windows years apart). |
| `frcc_2026_load_resource_plan.pdf` | [FRCC 2026 Load & Resource Plan](https://www.floridapsc.com/pscfiles/website-files/PDF/Utilities/Electricgas/TenYearSitePlans/2026/FRCC_RLRP.pdf) | `load_public_sources frcc` (pdfplumber, no LLM), pages 62, 85 | Form 13 "Proposed Transmission Lines" as of Jan 1, 2026: 23 lines of Duke Energy Florida, FPL, Tampa Electric, Lakeland, Seminole (p62) and PowerSouth ("PEC", p85). |
| `duke_energy_florida_2026_tysp.pdf` | [Duke Energy Florida 2026 TYSP](https://www.floridapsc.com/pscfiles/website-files/PDF/Utilities/Electricgas/TenYearSitePlans/2026/Duke%20Energy%20Florida.pdf) | `ingest.sh` (Gemini), pages 107-117 | Schedule 10 (201-211 repeats it; skipped). |
| `fpl_2026_tysp.pdf` | [FPL 2026 TYSP](https://www.floridapsc.com/pscfiles/website-files/PDF/Utilities/Electricgas/TenYearSitePlans/2026/Florida%20Power%20and%20Light%20Company.pdf) | `ingest.sh` (Gemini), pages 329-412, 439-440 | Schedule 10 (solar-site lines, statewide) + transmission narrative. 29 MB. |
| `city_of_tallahassee_2026_tysp.pdf` | [City of Tallahassee 2026 TYSP](https://www.floridapsc.com/pscfiles/website-files/PDF/Utilities/Electricgas/TenYearSitePlans/2026/City%20of%20Tallahassee.pdf) | `load_public_sources tallahassee` (pdfplumber, no LLM), page 49 | Table 4.2 Planned Transmission Projects: 2 lines (115 kV reconductor, Dec 2030). |

Not ingested: JEA's 2026 TYSP (Schedule 10: "None to Report"; its transmission chapter
describes only existing facilities).

SHA-256 of the committed originals:

```
b4b70abb4c217e8e2658c3bde7608a3d530e86a81279ccc572ced82a200e9f1c  eia860m_august_generator2026.xlsx
d3785576bb2f558f558931b7fea22503deaafc6d1f81cec25b8d471deb32cb2c  sertp_2026_preliminary_expansion_plan.pdf
890876d0faefd40576a0b5e598a804b54b4d8d2d56dd96fb7e40d5a406db0f46  desc_2024-2028_projects_2m_and_above.pdf
0dae2fc3a38462f0930cc2eb0acedca35e329cd0924e4749c81422bdc8602a12  georgia_power_2025_irp_vol3_public.pdf
fe01df4ed0691d55fd565784a7510ddfe4682316ff63fb70b963b934c5974f24  sperry_reference_overlaps.xlsx
```

## Loading

```bash
cd backend
# Structured sources, straight into DATABASE_URL (re-runnable: replaces its own last load)
.venv/bin/python -m scripts.load_public_sources all          # region: SC, GA, FL
.venv/bin/python -m scripts.load_public_sources sertp --areas SOUTHERN       # a subset
.venv/bin/python -m scripts.load_public_sources eia860m --states ALL         # nationwide
.venv/bin/python -m scripts.load_public_sources desc                         # DESC PDF
.venv/bin/python -m scripts.load_public_sources gpc                          # Georgia Power
.venv/bin/python -m scripts.load_public_sources frcc                         # Florida, Form 13
.venv/bin/python -m scripts.load_public_sources tallahassee                  # City of Tallahassee
.venv/bin/python -m scripts.load_public_sources all --dry-run --offline      # CSVs only

# Deployed (AWS Lightsail): nothing to run. extracted/*.csv ship in the image and the
# app (re)inserts a source at startup when its plan is missing or its CSV changed
# (AUTOLOAD_PUBLIC_SOURCES).

# Optional: the Duke Energy Florida and FPL TYSP schedules (more detail than Form 13) through
# the Gemini upload path (needs GEMINI_API_KEY and a running app)
bash ../source_docs/ingest.sh
```

**Gemini quota:** those pages are ~12 model requests. The free tier allows 5 per minute
(the app paces to `GEMINI_RPM`) and 20 per day per model; a failed plan can simply be
uploaded again once the quota resets.

## Region and timing

Only the region is loaded (`app/sources/region.py`: SC, GA, FL). EIA-860M is cut by plant
state; SERTP by the state of each located project (nearest county centre), keeping an
unplaced project only when its owner operates in region states alone (GTC, MEAG). The
utilities' own filings (DESC, Georgia Power, Florida) are the region by definition.

Matching then keeps only future work that builds at the same time: both projects in
service on or after `PLANNING_FROM` (default today) and building together for at least
`MIN_OVERLAP_DAYS` (30). Finished projects stay in the database but drop out of the map,
the Review list and the matches.

## How each source becomes project records

### EIA-860M (generation)

- Generators at one plant with the same planned operation month are one project
  (e.g. "Dega Solar and Storage (Batteries, Solar Photovoltaic, 400 MW)").
- Point = the plant latitude/longitude EIA publishes. In-service = planned operation month.
- Owner = EIA "Entity Name", canonicalized (`services/owners.py`) so "Tennessee Valley
  Authority" and SERTP's "TVA" are one utility.
- Citation: the workbook URL, sheet 2 ("Planned") as the page, and the spreadsheet row
  numbers plus balancing authority and status in the excerpt.

### SERTP (transmission)

- `app/sources/sertp.py` reads each "In-Service Year / Project Name / Description /
  Supporting Statement" block with pdfplumber. The balancing area comes from the page
  header; the owner from the name prefix in the Southern area (`GTC:`, `MEAG:`, `SOCO:`,
  `PS:`, `DU:`) or the area itself (Duke Energy Carolinas, Duke Energy Progress, LG&E and KU,
  TVA, AECI). The report gives no states, so each owner/area carries the states it covers.
- Endpoints are read from the name ("ADAMSVILLE - BUZZARD ROOST 230 KV REBUILD" ->
  Adamsville, Buzzard Roost); kV from the name or description; in-service year precision.
- Location (`app/sources/locate.py`), looked up once and cached in `backend/app/data/`:
  1. `osm_substations.csv`: named OSM `power=substation|plant` features for the SERTP
     states + FL (Overpass, `scripts/build_substation_cache.py`). Two matched endpoints ->
     midpoint of the line.
  2. `place_cache.json`: names OSM doesn't know as a substation are looked up as a place
     (Nominatim, Southeast only); the project is put at that place's **county centre**
     and marked approximate.
  3. Otherwise no point; the project is marked for review.
- Candidates outside the balancing area's rough territory box are ignored (FPL's "Martin
  Plant" in south Florida is not Alabama Power's Martin Dam), and two endpoints more than
  75 miles apart aren't averaged.
- Citation: report URL + page; the excerpt holds the full SERTP entry and how it was
  located (which OSM feature or which county).

Result for the 2026 report: 123 projects placed on matched OSM substations, 193
approximate (one endpoint only, or a county centre), 110 unplaced and marked for review.
The placement trail for every project is in `extracted/sertp_2026_preliminary_projects.csv`.
- Confidence: 0.95 placed on OSM substations, 0.8 approximate, 0.6 unplaced.

A planned line whose two endpoints both match OSM substations also gets a `route` (a
straight segment between them); matching measures closest points on it.

### ZIP search

- A ZIP is placed at its OpenStreetMap point (Nominatim `postalcode` search: the middle of
  the OSM addresses that carry it), from `app/data/zip_osm_points.csv`
  (`scripts/build_zip_cache.py`) or, failing that, a live lookup remembered per process.
- The Census ZCTA table (`app/data/zip_centroids.csv`) decides which ZIPs exist and is the
  fallback. Its internal points only have to fall inside the ZIP, so a big rural ZIP can
  land far from anyone: 33034's is in the Everglades, 18 miles west of Florida City. An OSM
  point more than 50 miles from the Census one is ignored as a different place.

### DESC and Georgia Power (the Sperry challenge pair)

- `app/sources/desc.py`: one project per page. Endpoints come from the title before the
  first voltage or colon ("Jasper – Okatie 230 kV #2: Construct" -> Jasper, Okatie); the
  in-service date is kept to the day; `cost_usd` is the "Total*" estimate.
- `app/sources/gpc_its.py`: Table 2 rows, names wrapping across lines and page breaks.
  Names follow the SERTP style, so SERTP's endpoint/voltage/kind parsing is reused. Need
  date to the day.
- Located the same way as SERTP, plus `app/data/curated_substations.csv`: substations OSM
  doesn't have, each with its source (Okatie from Sperry's reference table; DESC's
  "Queensboro" is OSM's "Queensborough").
- `app/data/place_overrides.csv` (guide Part 2, "a similarly-named substation in the wrong
  zone or county is a common false match"): per-utility corrections that win over the OSM
  and place lookups, each with its reason. A row pins a name to a point or a county
  centre, or blocks a wrong match so the name stays unplaced. It moved Georgia Power's
  metro-Atlanta Adamsville, Grady, Atkinson, Jack McDonough and Factory Shoals, and Plant
  Hammond (Floyd County), off same-named places by the SC border, and blocked Buzzard
  Roost from matching Santee Cooper's Buzzard Roost Dam in SC. Those misplacements had
  created 5 false DESC ↔ Georgia Power pairs.
- A DESC project whose title names only a new site is placed, approximately and with no
  route, on the line its description names ("Riverport Tap" is "Construct Okatie –
  Riverport 230 kV").
- Result: DESC 11 placed on substations, 31 approximate, 2 for review (Scout, Williams St);
  Georgia Power 39, 63 and 36. Every project in Sperry's reference table lands on the same
  substation Sperry used (within ~0.5 km), except Hooks, Purrysburg and Ft Johnson, which
  neither OSM nor Sperry could place.
- SERTP's own rows (for example GTC's Adamsville – Buzzard Roost) still carry the old
  placements until `load_public_sources sertp` is re-run with overrides for those owners.
- Georgia Power and SERTP's "Southern Company" rows are one planning entity
  (`services/owners.py`), so a project listed in both never pairs with itself.

### Florida (FRCC Form 13, City of Tallahassee)

- `app/sources/florida.py`. Form 13's two terminals are separate columns whose position
  differs between page 62 and page 85, so each row's terminal words are split at the widest
  gap between them. Owner codes are canonicalized (`DEF` Duke Energy Florida, `FPL`, `TEC`
  Tampa Electric, `LAK` City of Lakeland, `SEC` Seminole, `PEC` PowerSouth); joint lines
  ("DEF-SEC") keep both owners. Three FPL lines print "12/3033", read as 2033 and noted in
  the excerpt. In-service dates are month precision.
- Tallahassee's Table 4.2 names buses ("Sub 7", "Sub 16"), placed at Leon County's centre
  (approximate).
- Located like the others, with corrections from Duke's 2026 TYSP Schedule 10:
  - DEF's new Sweetwater, Turnpike and Lonesome Camp interconnections sit on its Holopaw
    lines in Osceola County, not at FPL's same-named Miami and St. Lucie substations.
  - Lakeland's Hamilton is in Polk County, not Hamilton County on the Georgia line.
- Result: 1 placed on substations, 17 approximate (Tallahassee's 2 included), 7 for review
  (new solar and storage sites OSM doesn't have yet).

A pdfplumber pass reads all 426 SERTP entries and the Florida tables, so no LLM is needed.
The Duke Energy Florida and FPL TYSP schedules can still go through the Gemini upload path
for more detail.

See [the current collision audit](current_collision_audit.md) for ownership review, source freshness, and future SC/Georgia matches.
