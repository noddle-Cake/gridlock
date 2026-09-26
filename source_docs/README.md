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
| `eia860m_august_generator2026.xlsx` | [EIA-860M, August 2026](https://www.eia.gov/electricity/data/eia860m/xls/august_generator2026.xlsx) (newest edition that downloads; the Sep-Dec links on the EIA page return 503) | `load_public_sources eia860m` (no LLM) | "Planned" sheet: 2,312 generators planned but not yet operating, with plant lat/long and planned operation month. Default load is nationwide: 2,311 generators (one row has no state or coordinates) at 1,649 plant / in-service-month sites (`--states` narrows it; the first load was AL, GA, MS, FL, TN, KY, NC, SC = 194 sites). Puerto Rico (`Planned_PR` sheet) is not loaded. |
| `sertp_2026_preliminary_expansion_plan.pdf` | [SERTP 2026 Preliminary Expansion Plan Report (Non-CEII)](https://www.southeasternrtp.com/docs/general/2026/2026_SERTP_Preliminary_Expansion_Plan_Report_(Non-CEII).pdf), dated 06/12/2026 | `load_public_sources sertp` (pdfplumber, no LLM) | 426 projects, in-service 2027-2036, by balancing area: AECI p1 (3), Duke Carolinas p2-16 (56), Duke Progress East p17-22 (17), Duke Progress West p23 (1), LG&E/KU p24-26 (10), Southern p27-102 (288: SOCO 204, GTC 67, MEAG 12, PowerSouth 4, Dalton 1), TVA p103-115 (51). |
| `desc_2024-2028_projects_2m_and_above.pdf` | [DESC Planned Transmission Projects $2M and above, 2024-2028](https://www.scrtp.com/assets/pdfs/home/2024-2028-2million-and-above-project-descriptions.pdf) (SCRTP; also in the Sperry Tech challenge kit) | `load_public_sources desc` (pdfplumber, no LLM) | 44 Dominion Energy South Carolina projects, one per page: title, project ID, description, need, status, planned in-service date and estimated cost by year. |
| `georgia_power_2025_irp_vol3_public.pdf` | Georgia Power 2025 IRP, Volume 3 (public disclosure), [Georgia PSC Docket #56002](https://psc.ga.gov/search/facts-docket/?docketId=56002); from the Sperry Tech challenge kit | `load_public_sources gpc` (pdfplumber, no LLM), pages 177-190 | Table 2 "Georgia ITS 10 Year Plan Project List": 208 rows. The 138 Georgia Power rows (sponsor GPC or SAV) are loaded; GTC/MEAG/DU rows are other utilities already listed in SERTP. |
| `sperry_reference_overlaps.xlsx` | Sperry Tech challenge kit (`Projects_Overlaps.xlsx`) | not loaded; used by `tests/test_desc_gpc.py` | Sperry's hand-built reference: 5 DESC + 5 Georgia Power projects and the 6 overlaps between them. The acceptance test requires all 6 to be flagged. |
| `frcc_2026_load_resource_plan.pdf` | [FRCC 2026 Load & Resource Plan](https://www.floridapsc.com/pscfiles/website-files/PDF/Utilities/Electricgas/TenYearSitePlans/2026/FRCC_RLRP.pdf) | `ingest.sh` (Gemini), pages 62, 85 | Form 13 "Proposed Transmission Lines", every Florida utility. |
| `duke_energy_florida_2026_tysp.pdf` | [Duke Energy Florida 2026 TYSP](https://www.floridapsc.com/pscfiles/website-files/PDF/Utilities/Electricgas/TenYearSitePlans/2026/Duke%20Energy%20Florida.pdf) | `ingest.sh` (Gemini), pages 107-117 | Schedule 10 (201-211 repeats it; skipped). |
| `fpl_2026_tysp.pdf` | [FPL 2026 TYSP](https://www.floridapsc.com/pscfiles/website-files/PDF/Utilities/Electricgas/TenYearSitePlans/2026/Florida%20Power%20and%20Light%20Company.pdf) | `ingest.sh` (Gemini), pages 329-412, 439-440 | Schedule 10 (solar-site lines, statewide) + transmission narrative. 29 MB. |
| `city_of_tallahassee_2026_tysp.pdf` | [City of Tallahassee 2026 TYSP](https://www.floridapsc.com/pscfiles/website-files/PDF/Utilities/Electricgas/TenYearSitePlans/2026/City%20of%20Tallahassee.pdf) | `ingest.sh` (Gemini), pages 47-49 | Table 4.2 Planned Transmission Projects. |

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
.venv/bin/python -m scripts.load_public_sources all
.venv/bin/python -m scripts.load_public_sources sertp --areas SOUTHERN TVA   # a subset
.venv/bin/python -m scripts.load_public_sources eia860m --states GA AL TN   # one region
.venv/bin/python -m scripts.load_public_sources desc                         # DESC PDF
.venv/bin/python -m scripts.load_public_sources gpc                          # Georgia Power
.venv/bin/python -m scripts.load_public_sources all --dry-run                # CSVs only

# Deployed (AWS Lightsail): nothing to run. extracted/*.csv ship in the image and the
# app (re)inserts a source at startup when its plan is missing or its CSV changed
# (AUTOLOAD_PUBLIC_SOURCES).

# Florida PDFs through the Gemini upload path (needs GEMINI_API_KEY and a running app)
bash ../source_docs/ingest.sh
```

**Gemini quota:** the Florida pages are ~12 model requests. The free tier allows 5 per
minute (the app paces to `GEMINI_RPM`) and 20 per day per model; a failed plan can simply
be uploaded again once the quota resets.

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
- Result: DESC 11 placed on substations, 22 approximate, 11 for review; Georgia Power 39,
  62 and 37. Every project in Sperry's reference table lands on the same substation Sperry
  used (within ~0.5 km), except Hooks, Purrysburg and Ft Johnson, which neither OSM nor
  Sperry could place.
- Georgia Power and SERTP's "Southern Company" rows are one planning entity
  (`services/owners.py`), so a project listed in both never pairs with itself.

A pdfplumber pass reads all 426 entries, so no LLM is needed for SERTP. Messier filings
(the Florida TYSPs) go through the existing Gemini upload path.
