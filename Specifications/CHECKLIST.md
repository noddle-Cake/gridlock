# Gridlock challenge: completion checklist

Audit of `master` at `bc3a068` (PR #11) against the Sperry Tech challenge, 2026-09-26. Work on
branch `worktree-spec-checklist` is marked **fixed in this branch**.

**Requirement sources**
- `Sperry-Tech-Challenge/ShellHacks_Challenge_Gridlock.docx`: the challenge brief.
- `Useful instructions`: the extended brief, with 40 km closest-point overlap and 4 distance tiers.
- `Sperry-Tech-Challenge/Finding_Real_Locations_Guide.docx`: locate, confirm, then measure.
- `Sperry-Tech-Challenge/Projects_Overlaps.xlsx`: Sperry's answer key, 5 DESC + 5 GPC projects with 6 overlaps.
- `.kiro/specs/gridmerge/`: the team's own requirements and tasks.

**How it was checked**

| | Before (`bc3a068`) | After (this branch) |
|---|---|---|
| Backend `pytest` (PostGIS) | 194 passed | 216 passed, `ruff` clean |
| Frontend `vitest` | 68 passed | 79 passed, `tsc` + `oxlint` clean |
| Live run | every committed source loaded, UI reviewed in Chrome | same, re-checked after each fix |
| Sources | nationwide EIA-860M, all of SERTP, DESC, Georgia Power (2,075 projects) | the Southeast (SC, GA) plus Florida: DESC, Georgia Power, SERTP's SC/GA/FL rows, FRCC Form 13, Tallahassee, EIA-860M in SC/GA/FL (474 projects) |
| What counts as a match | within 40 km, any timing | within 40 km **and** future work **and** building at the same time for 30+ days |
| Matches | 4,524 nationwide; DESC ↔ GPC 57, 5 of them false | 580 in the region; DESC ↔ GPC 0 (see section 0) |

Legend: `[x]` done · `[~]` partly done · `[ ]` open · **P0** before demo · **P1** should · **P2** nice to have.

---

## 0. Latest revamp: Southeast + Florida sources, future work that builds at the same time

Requested after the first pass: Southeast sources only (Dominion SC, Georgia, then Florida
companies); matches must be close in time and overlap; past projects (done) excluded.

- [x] **V1 · Sources limited to the region (SC, GA, FL).** *(this branch)*
  - Added `app/sources/region.py`.
  - EIA-860M is cut to SC/GA/FL plants: 1,649 → 78.
  - SERTP keeps projects located in the region: 426 → 189.
  - DESC and Georgia Power are unchanged.
- [x] **V2 · Florida companies added, deterministically.** *(this branch)*
  - `app/sources/florida.py` reads FRCC Form 13 (Duke Energy Florida, FPL, Tampa Electric, Lakeland, Seminole, PowerSouth: 23 lines) and Tallahassee's Table 4.2 (2 lines), with no LLM.
  - False placements corrected with sources: DEF's Sweetwater, Turnpike and Lonesome Camp had matched FPL's Miami and St. Lucie substations, and Lakeland's Hamilton had matched Hamilton County on the Georgia line.
- [x] **V3 · Future work only.** *(this branch)*
  - A match needs both projects in service on or after `PLANNING_FROM` (default today).
  - `/projects`, the map and Review hide finished projects (`?include_past=true` shows them).
- [x] **V4 · Timing required.** *(this branch)*
  - A match needs both projects building at the same time for at least `MIN_OVERLAP_DAYS` (30).
  - Pairs years apart (e.g. 8.4 years) or undated are no longer matches.
  - The same test applies to `/overlaps`, `/export`, briefs (404 for a non-match) and the post-edit re-check.
- [x] **V5 · Clear timing in the UI.** *(this branch)*
  - A green banner states the rules.
  - Every card shows "N months building together" and "Both building Jun 2026 – Dec 2027 · X% of their build time".
  - Map connectors say the same; the pair panel draws both build windows.
- [x] **V6 · Default view.** *(this branch)* The app opens on every loaded (Southeast) utility. "Only Dominion SC ↔ Georgia Power" stays in the utility menu.
- **Consequences:**
  - **Dominion SC ↔ Georgia Power has 0 matches.** DESC's public list is a 2024–2028 budget, and 28 of its 44 projects are already in service. Every future Georgia Power project near DESC's future work is due 2033–2034, so none builds at the same time.
  - **Sperry's six reference overlaps are no longer matches** (R8). They are still found within range, which the acceptance test checks.
- [ ] **V7 · P1 · Decision: Georgia ITS partners pairing with each other.**
  - About 400 of the 580 matches are GTC ↔ Southern Company / Georgia Power / MEAG: the same jointly planned Georgia ITS lines listed by each owner (e.g. "Avery – Hopewell 115 kV Reconductor" appears under both Georgia Power and GTC).
  - Treating the ITS partners as one planning entity (`owners.PLANNING_ENTITY`) would leave the cross-utility matches: SC ↔ GA, GA ↔ FL, and Florida utilities with each other.
- [ ] V8 · P2 · EIA-860M developer projects pair with their own phases (SR Bacon II ↔ SR Bacon III, Placid Solar ↔ Placid Solar II). Grouping phases by developer or site would remove them.
- [ ] V9 · P2 · 7 Florida lines are unplaced: new solar and storage interconnections OSM doesn't have yet (Banner – Radiant, Higdon – Birch, the FPL Oasis 500 kV lines). The Duke Energy Florida Schedule 10 text and the FPL TYSP could place them.

---

## 1. Core requirements

| # | Requirement | Status | Evidence |
|---|---|---|---|
| R1 | Ingest public future-construction data from at least 2 utilities | [x] | DESC SCRTP PDF (44 projects) and Georgia Power 2025 IRP Vol 3, Table 2 (138 projects), plus SERTP's SC/GA/FL rows, FRCC Form 13, Tallahassee's TYSP and EIA-860M in SC/GA/FL. All parsed deterministically and cited per page. |
| R2 | Geographic overlap within 40 km (25 mi), closest points | [x] | `ST_DWithin` over route-or-point shapes. Each pair now also returns the closest-point `link`, which the map draws. |
| R3 | Rank by Sperry's distance tiers | [x] | `matching.TIERS`/`rank_key`; each card shows its tier label. |
| R4 | Timeline overlap, used together with geography | [x] | **Required** for a match since section 0: both projects are future work, building together for 30+ days. Build-window IoU is 30% of the composite. Cards, connectors and the pair panel show the shared build time. |
| R5 | **Required:** interactive UI showing the utilities' projects, highlighting overlaps | [x] | Opens on the Southeast, with company colours (the utilities on screen get the most distinct ones), paired markers emphasised, and closest-point connectors. |
| R6 | **Required:** ranked list of top coordination opportunities | [x] | Ranked pair list with tier, score, shared build time, value and sort options. |
| R7 | Find the real matches, since most of the data does not overlap | [x] | 580 region matches out of 474 × 473 project combinations; false placements removed (C1, V2). |
| R8 | Sperry's reference overlaps OVL_1–OVL_6 | [~] | All found within range (`tests/test_desc_gpc.py`: OVL_1 touching, OVL_2/3 4.9 km, OVL_4 11.0 km, OVL_5/6 13.6 km), but **none is a match** under the timing rules (section 0): each involves DESC work due by 2025, or windows years apart. |
| R9 | Public, non-CEII data only | [x] | `source_docs/README.md` |
| R10 | Guide Part 2: confirm each location against the filing; flag unconfirmed ones as lower-confidence | [x] | Sourced overrides (C1) and a description re-read (C2). Unconfirmed projects keep `approximate` and confidence 0.8. |

### Core-quality items

- [x] **C1 · P0 · False placements created 5 false DESC ↔ GPC pairs.** *(fixed in this branch)*
  - Added `backend/app/data/place_overrides.csv`: per-planning-entity pins, county centres or blocks, each with its reason. They win over the OSM and place lookups.
  - Fixed Georgia Power's Adamsville, Buzzard Roost (blocked from Santee Cooper's SC dam), Factory Shoals, Jack McDonough, Atkinson, Hammond and Grady.
  - Guarded by `test_metro_atlanta_substations_are_not_placed_by_the_sc_border`.
  - Follow-up (P2): SERTP's own rows (e.g. GTC's Adamsville – Buzzard Roost) keep the old placements until `load_public_sources sertp` is re-run with override rows for those owners.
- [~] **C2 · P1 · Unplaced projects can never match.** *(mostly fixed in this branch)*
  - DESC unplaced went from **11 to 2**, via:
    - Overrides for Wateree, Killian, Edenwood, Summerville, Union Pier, Coit and Gills Creek.
    - Placing a project on the line its description names: "Riverport Tap: Construct Okatie – Riverport 230 kV", Dawson, Goose Creek Reservoir.
  - GPC unplaced went from 37 to 36. Still open:
    - [ ] DESC Scout and Williams St (the descriptions name several sites).
    - [ ] GPC Purrysburg (SC side, across from McIntosh), which neither OSM nor Sperry could place.
    - [ ] GPC "Cc -" customer-connection projects (Hyundai Metaplant, QTS, Microsoft; locations are public news, but not in the filing).
    - [ ] Titles like "Little Ogeechee 230 - 115Kv: Relay Modernization" split on the dash inside the voltage (endpoint becomes "Little Ogeechee 230").
- [x] **C3 · P2 · The spec versions disagree** (25 mi center-to-center vs 40 km closest points). The README "Overlap definition" note now records the choice. *(fixed in this branch)*

---

## 2. Bonus

- [x] **B1 · Rough cost / impact estimate** for every flagged pair (`services/impact.py`), with assumptions. Shown in the panel and on cards, and exported. Also included in template briefs.
- [ ] **B2 · P2 · Portfolio roll-up:** one headline total for the focused utility pair.
- [x] **B3 · P1 · Coordination brief without Gemini.** With no key, "Generate brief" gave a 502. It now drafts a facts-only brief (distance, timing, tier opportunity, value), stored with `source = "template"` and labelled in the UI. A configured model that fails still returns 502/504. Also fixed: briefs for pairs with no shared window lost their proposal sentence (the facts check wanted in-service years). *(fixed in this branch)*
- [x] B4 · CSV/PDF export (Kiro 14.1). It now follows the utility focus.
- [x] B5 · 3+ utilities (Kiro 15).
- [x] B6 · Existing-grid reference layers (HIFLD and OpenInfraMap).
- [x] B7 · CI/CD to AWS Lightsail with health-checked rollback (Kiro 17.1).
- [x] B8 · Line geometry (Kiro 16.1/16.2): routes, closest-point distance and a test. *(Kiro tasks updated in this branch)*
- [ ] B9 · P2 · Custom domain with TLS (Kiro 17.2), and an HTTPS smoke test (17.3).
- [ ] B10 · P2 · Golden-set extraction accuracy harness (Kiro 10.3).
- [ ] B11 · P2 · Export property tests (Kiro 14.2).
- [ ] B12 · P2 · Snap straight planned-line routes to the HIFLD corridor they rebuild.

---

## 3. UI issues (live review)

- [x] **U1 · P0 · The two utilities couldn't be told apart.** The default is now "Color by: Company", and the utilities on screen take the leading palette slots: DESC blue, Georgia Power orange (before: two oranges). *(fixed in this branch)*
- [x] **U2 · P1 · The legend card covered the SC side of the map.** Fitting and flying now pad the right edge by the legend stack's width, capped at 40% of the map. *(fixed in this branch)*
- [x] **U3 · P1 · Connectors were drawn center-to-center.** They now run between the closest points, and touching pairs get a ring at the touch point. The Hooks–Thurmond ↔ Evans–Thurmond pair used to show a 6 km line for "0.0 km". *(fixed in this branch)*
- [x] **U4 · P1 · Timeline overlap was never drawn.** Added a build-window strip in the pair panel. *(fixed in this branch)*
- [x] **U5 · P1 · The Review tab ignored the utility focus and search.** Its badge went from 158 nationwide to 48 in focus. *(fixed in this branch)*
- [x] **U6 · P1 · Export ignored the utility focus** (4,524 pairs instead of those on screen). *(fixed in this branch)*
- [x] U7 · P2 · The power-grid layer blurred after flying to a pair.
  - The layer had no `maxZoom`, so Leaflet gave each zoom level a z-index of `NaN`. It also fetched tiles for every zoom level a fly passed through. Both are fixed.
  - A stretched parent tile can still linger in a *hidden* tab (fade frames paused), which is what the automated review saw.

  *(fixed in this branch)*
- [x] U8 · P2 · "← Back to list" kept the detail's scroll offset. The list now returns to where it was, and pairs open at the top. *(fixed in this branch)*
- [ ] U9 · P2 · Near-duplicate cards: one site can show up to 6 cards at 11.0 km (DESC Stevens Creek – Hooks 2024/2025 phases × GPC Evans – Thurmond #5/#6 and Evans – Thomson). Group by site.
- [ ] U10 · P2 · The Georgia Power source link opens the PSC docket page, so `#page=` is lost. Serve or link the committed PDF instead.
- [ ] U11 · P2 · Review → Radar remounts the whole map, and the renderer stalls briefly. Keep it mounted and hide it instead.
- [ ] U12 · P2 · Changing `#pair=` in an open tab (a pasted link) doesn't open the pair; only a page load does. Listen for `hashchange`.
- [x] U13 · P2 · The utility filter chip said "DESC ↔ Georgia Power". "DESC" is filing shorthand that viewers don't recognise, so it now reads "Dominion SC ↔ Georgia Power". *(fixed in this branch)*

---

## 4. Inefficiencies

- [x] **E1 · P0 · `/overlaps` sent 11.5 MB on every band change to show 57 pairs.**
  - Added a `utility=` filter applied in SQL. The app waits for the utility focus before its first query and asks only for the shown utilities.
  - Added gzip in the app (`COMPRESS_RESPONSES`; off in the deploy stack, where Caddy serves zstd).
  - Result: 8 KB for the default view. The nationwide view is 828 KB gzipped.

  *(fixed in this branch)*
- [x] E2 · P1 · `/projects` is 2.2 MB raw, but now 219 KB gzipped. *(mitigated in this branch)* Splitting out `raw_excerpt` remains a P2 option.
- [ ] E3 · P2 · Every pair embeds both full projects; referencing ids would shrink the nationwide payload further.
- [ ] E4 · P2 · Overlaps are recomputed on every request (0.6–1.0 s nationwide); cache per `(radius, bands, utilities)`.
- [x] E5 · Batched inserts and a one-query re-match after edits (PR #9).

---

## 5. Docs

- [x] D1 · README scoring weights now match the code (0.55 / 0.30 / 0.075 / 0.075). *(fixed in this branch)*
- [x] D2 · README test counts (216 backend, 79 frontend). *(fixed in this branch)*
- [x] D3 · Kiro `tasks.md`: 16.1, 16.2 and 17.1 marked done. *(fixed in this branch)*
- [x] D4 · README demo walkthrough: the six reference overlaps, the pair panel, and Riverport. *(fixed in this branch)*
- [ ] D5 · P2 · Setup note: the local `backend/.venv` predates `pdfplumber` in `requirements.txt`. Re-run `pip install -r requirements-dev.txt` before `load_public_sources`.

---

## 6. Suggested next steps

1. V7: decide whether Georgia ITS partners (GTC, MEAG, Georgia Power) count as one planning entity, which drops about 400 same-line matches. Then V8 (developer phases) and V9 (unplaced Florida lines).
2. C2 leftovers (Purrysburg, the "Cc -" customer projects, the "230 - 115Kv" title split), then re-run the SERTP load with override rows for GTC and Southern Company (C1 follow-up).
3. U9 group near-duplicate cards · B2 portfolio roll-up: most visible for a demo.
4. E3/E4 if the nationwide view matters; U10–U12 polish; B9–B12 stretch.
