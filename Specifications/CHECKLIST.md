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
| Backend `pytest` (PostGIS) | 194 passed | 206 passed, `ruff` clean |
| Frontend `vitest` | 68 passed | 77 passed, `tsc` + `oxlint` clean |
| Live run | every committed source loaded, UI reviewed in Chrome | same, re-checked after each fix |
| DESC ↔ GPC pairs | 57, of which 5 false | 62, no known false ones, 11 new from Riverport Tap |
| Default view payload (`/overlaps`) | 11.5 MB of JSON, all 4,524 pairs nationwide | 8 KB gzipped, only the 62 pairs shown |

Legend: `[x]` done · `[~]` partly done · `[ ]` open · **P0** before demo · **P1** should · **P2** nice to have.

---

## 1. Core requirements

| # | Requirement | Status | Evidence |
|---|---|---|---|
| R1 | Ingest public future-construction data from at least 2 utilities | [x] | DESC SCRTP PDF (44 projects) and Georgia Power 2025 IRP Vol 3, Table 2 (138 projects), parsed deterministically and cited per page. SERTP, EIA-860M and Florida TYSPs are also loaded. |
| R2 | Geographic overlap within 40 km (25 mi), closest points | [x] | `ST_DWithin` over route-or-point shapes. Each pair now also returns the closest-point `link`, which the map draws. |
| R3 | Rank by Sperry's distance tiers | [x] | `matching.TIERS`/`rank_key`; each card shows its tier label. |
| R4 | Timeline overlap as a strong secondary signal | [x] | Build-window IoU is 30% of the composite, plus `time_gap_days`. The pair panel now **draws** both build windows with the shared stretch hatched. |
| R5 | **Required:** interactive UI showing both utilities' projects, highlighting overlaps | [x] | Opens on DESC ↔ GPC, now coloured blue and orange (before: both orange), with paired markers emphasised and closest-point connectors. |
| R6 | **Required:** ranked list of top coordination opportunities | [x] | Ranked pair list with tier, score, timing, value and sort options. |
| R7 | Find the real matches, since most of the data does not overlap | [x] | 62 DESC ↔ GPC pairs; false matches removed (C1). |
| R8 | Sperry's reference overlaps OVL_1–OVL_6 all flagged | [x] | `tests/test_desc_gpc.py`. OVL_1 is touching; OVL_2 and OVL_3 are 4.9 km; OVL_4 is 11.0 km; OVL_5 and OVL_6 are 13.6 km. The README demo walkthrough maps each one. |
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
- [x] D2 · README test counts (206 backend, 77 frontend). *(fixed in this branch)*
- [x] D3 · Kiro `tasks.md`: 16.1, 16.2 and 17.1 marked done. *(fixed in this branch)*
- [x] D4 · README demo walkthrough: the six reference overlaps, the pair panel, and Riverport. *(fixed in this branch)*
- [ ] D5 · P2 · Setup note: the local `backend/.venv` predates `pdfplumber` in `requirements.txt`. Re-run `pip install -r requirements-dev.txt` before `load_public_sources`.

---

## 6. Suggested next steps

1. C2 leftovers (Purrysburg, the "Cc -" customer projects, the "230 - 115Kv" title split), then re-run the SERTP load with override rows for GTC and Southern Company (C1 follow-up).
2. U9 group near-duplicate cards · B2 portfolio roll-up: most visible for a demo.
3. E3/E4 if the nationwide view matters; U10–U12 polish; B9–B12 stretch.
