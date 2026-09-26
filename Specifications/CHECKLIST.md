# Gridlock challenge: completion checklist

Audit of `master` at `bc3a068` (PR #11) against the Sperry Tech challenge, dated 2026-09-26.

**Requirement sources**
- `Sperry-Tech-Challenge/ShellHacks_Challenge_Gridlock.docx`: the challenge brief.
- `Useful instructions`: the extended brief, with 40 km closest-point overlap and 4 distance tiers.
- `Sperry-Tech-Challenge/Finding_Real_Locations_Guide.docx`: locate, confirm, then measure.
- `Sperry-Tech-Challenge/Projects_Overlaps.xlsx`: Sperry's answer key, 5 DESC + 5 GPC projects with 6 overlaps.
- `.kiro/specs/gridmerge/`: the team's own requirements and tasks.

**How this was checked**
- Backend: `pytest` against PostGIS, **194 passed**.
- Frontend: `vitest`, **68 passed**.
- Live run: the app ran on a fresh database with every committed source loaded (EIA-860M, SERTP, 44 DESC and 138 Georgia Power projects), and the UI was reviewed in Chrome.

Legend: `[x]` done and verified · `[ ]` open · **P0** fix before demo · **P1** should fix · **P2** nice to have.
Items fixed on branch `worktree-spec-checklist` are marked *(fixed in this branch)*.

---

## 1. Core requirements

| # | Requirement | Status | Evidence |
|---|---|---|---|
| R1 | Ingest public future-construction data from at least 2 utilities | [x] | DESC SCRTP PDF (44 projects) and Georgia Power 2025 IRP Vol 3, Table 2 (138 projects), parsed with pdfplumber and cited per page. SERTP, EIA-860M and Florida TYSPs are also loaded. |
| R2 | Geographic overlap: flag pairs within 40 km (25 mi), measured between closest points | [x] | `ST_DWithin` over route-or-point shapes (`repository.py`). Planned lines with both ends located are routed, so a crossing measures 0 km. |
| R3 | Rank by distance tier: touching → must coordinate, <1.6 km → share land, <8 km → share site logistics, <40 km → share crews | [x] | `matching.TIERS`, `rank_key`. Each card shows its tier label. |
| R4 | Timeline overlap as a strong secondary signal, used together with geography | [x] | Build-window IoU (`timing.py`) is 30% of the composite. `time_gap_days` matches Sperry's "time gap (day)" column. |
| R5 | **Required:** interactive UI showing both utilities' planned projects, highlighting overlaps | [x] | Leaflet map with pan, zoom, hover and click. Paired markers are emphasised and connected. Opens focused on DESC ↔ Georgia Power. The issues in section 3 still hurt this. |
| R6 | **Required:** ranked list of the top coordination opportunities | [x] | Pair list sorted by tier, then composite, then distance. Also sortable by distance, time overlap and start date. |
| R7 | Expect most of the dataset NOT to overlap; find the real matches | [x] | 57 DESC ↔ GPC pairs out of 182 × 181 combinations. |
| R8 | Sperry's reference overlaps (OVL_1–OVL_6) are all flagged | [x] | OVL_1 is touching at the shared Thurmond substation. OVL_2 and OVL_3 are 4.9 km, OVL_4 is 11.0 km, OVL_5 and OVL_6 are 13.6 km. `tests/test_desc_gpc.py` guards this. |
| R9 | Only public, non-CEII data | [x] | See `source_docs/README.md`. The GPC file is the public-disclosure version, with cost columns redacted. |
| R10 | Guide Part 2: confirm each location against the filing; flag unconfirmed ones as lower-confidence | [~] | Approximate or unplaced projects get lower confidence, and each placement is recorded in the excerpt. **Some false matches are still accepted** (item C1). |

### Core-quality gaps (the "find the real matches" part)

- [ ] **C1 · P0 · False placements create false DESC ↔ GPC pairs.** 5 of 57 pairs are wrong. Georgia Power substations in metro Atlanta match same-named places near the SC border:
  - `BUZZARD ROOST` matches Buzzard Roost Dam Substation in SC (Lake Greenwood).
  - `ADAMSVILLE` is placed at the McDuffie County, GA centre, near Augusta.
  - `HAMMOND` is placed at the Anderson County, SC centre, though it is Plant Hammond in Floyd County, GA.
  - Also wrong but far from DESC: `GRADY` goes to Grady County and `ATKINSON` to Atkinson County; both are in Atlanta.

  Curated rows can only *add* candidates, never veto a wrong one, so this needs sourced overrides that take precedence. *(fixed in this branch)*
- [ ] **C2 · P1 · 11 DESC and 37 GPC projects are unplaced and can never match.** Cross-border candidates that matter most:
  - DESC `Riverport Tap` (Jasper County, SC, across from Savannah).
  - GPC `Purrysburg` (SC side).
  - DESC `Wateree – Killian` (OSM has a Wateree Substation, but a same-name tie across states leaves it unresolved).
  - DESC `Summerville` ×2 (single-name, several same-named places).
- [ ] **C3 · P2 · The two spec versions disagree on method.** The docx says center-to-center under 25 mi; `Useful instructions` says closest points under 40 km. The app uses closest points under 40 km, which is the stricter, newer wording, and reports `time_gap_days` like the reference table. The README should say so explicitly.

---

## 2. Bonus

- [x] **B1 · Rough cost / impact estimate for flagged opportunities** (`services/impact.py`). Tier-based sharing items, ROW acres for routed pairs, DESC's published costs, and an "if schedules aligned" figure. Shown in the pair panel and on every card, and exported as `value_*_usd`.
- [ ] **B2 · P2 · Portfolio roll-up.** Total rough value across the focused utility pair, so there is a single headline number for the demo.
- [ ] **B3 · P1 · Coordination brief without Gemini.** "Generate brief" returns a 502 with no `GEMINI_API_KEY`. A deterministic template brief would keep the demo working offline. *(fixed in this branch)*
- [x] B4 · CSV / PDF export (Kiro 14.1).
- [x] B5 · 3+ utilities (Kiro 15). Nationwide EIA plus SERTP across 978 companies.
- [x] B6 · Existing-grid reference layers (HIFLD snapshot and OpenInfraMap power tiles), which the challenge calls an optional base layer.
- [x] B7 · CI/CD to AWS Lightsail with health-checked rollback (Kiro 17.1).
- [ ] B8 · P2 · Custom domain with TLS (Kiro 17.2), and a deployment smoke test asserting HTTPS (17.3).
- [ ] B9 · P2 · Golden-set extraction accuracy harness (Kiro 10.3).
- [ ] B10 · P2 · Export property tests (Kiro 14.2) and line-geometry example tests (16.2).
- [ ] B11 · P2 · Snap straight planned-line routes to the HIFLD corridor they rebuild (README "Not yet done").

---

## 3. UI issues (live review)

- [ ] **U1 · P0 · The two utilities can't be told apart.**
  - The default "Color by: Type" paints DESC and Georgia Power the same orange (both mostly transmission lines).
  - Switching to "Company" gives DESC `#eb6834` and Georgia Power `#eda100`: two oranges, because palette slots are assigned alphabetically across all 978 companies.
  - Fix: default to Company, and give the shown utilities the first, most distinct slots. *(fixed in this branch)*
- [ ] **U2 · P1 · The legend card covers the SC side of the map** at the default framing, where DESC's Columbia-area projects sit. *(fixed in this branch)*
- [ ] **U3 · P1 · Pair connectors are drawn center-to-center, but distance is measured closest-point.** Example: Hooks–Thurmond ↔ Evans–Thurmond is "0.0 km apart" yet shows a ~6 km connector. Fix: draw the shortest line, and mark the touch point for 0 km pairs. *(fixed in this branch)*
- [ ] **U4 · P1 · Timeline overlap is never shown visually.** The pair panel lists dates, but the two build windows and their shared stretch are not drawn. `TimelineView.tsx` exists but isn't mounted anywhere. *(fixed in this branch: build-window bars in the pair panel)*
- [ ] **U5 · P1 · The Review tab ignores the utility focus and search box.**
  - It lists e.g. Associated Electric Cooperative while "DESC ↔ Georgia Power" is selected.
  - The "Review 158" badge counts projects nationwide.

  *(fixed in this branch)*
- [ ] **U6 · P1 · Export CSV / PDF ignores the utility focus.** It downloads all 4,524 pairs nationwide instead of the 57 on screen. *(fixed in this branch)*
- [ ] U7 · P2 · After flying to a pair, the power-grid layer is blurry for ~3 s. It shows stretched low-zoom tiles and fetches tiles at every intermediate zoom of the animation. *(fixed in this branch)*
- [ ] U8 · P2 · "← Back to list" keeps the detail view's scroll offset, so the list reopens part-way down.
- [ ] U9 · P2 · Near-duplicate cards. DESC lists Stevens Creek – Hooks twice (2024 and 2025 phases) and GPC lists Evans – Thurmond #5/#6 and Evans – Thomson twice, so one site shows up to 6 cards at 11.0 km. Group by site, or collapse same-name pairs.
- [ ] U10 · P2 · The Georgia Power source link opens the PSC docket search page, so the page anchor (`#page=189`) is lost. Link the PDF itself, e.g. the committed copy.
- [ ] U11 · P2 · Switching Review → Radar remounts the whole map (about 2.7k markers and all pairs), and the renderer stalls briefly. Keep the map mounted and hide it instead.

---

## 4. Inefficiencies

- [ ] **E1 · P0 · `/overlaps` sends 11.5 MB of JSON (4,524 pairs nationwide) on every band change, while the default view shows 57.**
  - There is no server-side utility filter.
  - The app itself doesn't compress; only Caddy in production does.
  - Fix: a `utility=` filter applied in SQL, plus GZip in the app. *(fixed in this branch)*
- [ ] E2 · P1 · `/projects` is 2.2 MB, much of it `raw_excerpt`, which only the Review table uses.
- [ ] E3 · P2 · Every pair embeds both full `ProjectDTO`s. Referencing project ids and joining client-side with `/projects` would roughly halve the payload again.
- [ ] E4 · P2 · Overlaps are recomputed on every request (0.6–1.0 s nationwide). Cache per `(radius, bands, utilities)` and invalidate on edit or ingest.
- [x] E5 · Planned-project inserts are batched, and the post-edit re-match is one query (PR #9).

---

## 5. Docs drift

- [ ] D1 · README says weights 0.60 / 0.25 / 0.075 / 0.075; the code (`scoring.WEIGHTS`) uses 0.55 / 0.30. *(fixed in this branch)*
- [ ] D2 · README says 120 backend and 27 frontend tests; the suites now run 194 and 68. *(fixed in this branch)*
- [ ] D3 · `.kiro/specs/gridmerge/tasks.md` still shows 16.1 (routes) and 17.1 (Lightsail deploy) as open; both are implemented. *(fixed in this branch)*
- [ ] D4 · P2 · A short demo script in the README: open on DESC ↔ GPC, walk the 6 reference overlaps, show one value estimate.

---

## 6. Order of work

1. U1 colours · E1 payload · C1 false placements (P0)
2. U3 connector · U4 build windows · U5 review scope · U6 export scope · U2 legend · B3 offline brief (P1)
3. C2 more placements · U7–U11 · E2–E4 · docs (P1–P2)
