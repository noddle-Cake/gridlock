"""DESC and Georgia Power sources, and Sperry's reference overlaps as an acceptance test."""

from __future__ import annotations

import re
from datetime import date
from pathlib import Path

import pytest

from app.db import repository as repo
from app.services import matching
from app.services.owners import planning_entity
from app.sources import desc, gpc_its, snapshot
from tests.conftest import requires_db, run_db

ROOT = Path(__file__).resolve().parents[2]
REFERENCE = ROOT / "source_docs" / "sperry_reference_overlaps.xlsx"

DESC_PAGE = """Project 23 of 44
Dominion Energy South Carolina
Planned Transmission Projects $2M and above Total
5 Year Budget
Jasper – Okatie 230 kV #2: Construct
Project ID
6360
Project Description
Construct a second Jasper – Okatie 230 kV line.
Project Need
This project is needed to improve system performance.
Project Status
In Progress
Planned In-Service Date
12/31/25
Estimated Project Cost
Previous 2024 2025 2026 2027 2028 Total*
$1,000,000 $12,000,000 $10,787,423 $0 $0 $0 $23,787,423
*Total Estimated Amount applied to 2025 Rate Base Calculation"""


def test_desc_page_parses():
    e = desc.parse_page_text(DESC_PAGE, page=23)
    assert e.title == "Jasper – Okatie 230 kV #2: Construct"
    assert e.endpoints == ["Jasper", "Okatie"] and e.kind == "transmission line"
    assert e.voltage_kv == 230 and e.status == "In Progress"
    assert e.in_service == (date(2025, 12, 31), date(2025, 12, 31))
    assert e.cost_usd == 23_787_423


@pytest.mark.parametrize(("title", "endpoints"), [
    ("Okatie 230-115kV Substation, Jasper – Yemassee 230kV #1 Fold-in", ["Okatie"]),
    ("Stevens Creek - Hooks 115kV/LR Plumb Branch 46kV Rebuilds", ["Stevens Creek", "Hooks"]),
    ("Harleyville 115KV Transmission Tap – Construct (1.4 miles)", ["Harleyville"]),
    ("Edenwood Sub: #1 & #2 230-115kV Autobanks, Replace with 336MVA", ["Edenwood"]),
    ("Canadys-Ritter 115KV-Rebld SPDC 230/115KV 1272 (Approx 18 Miles)", ["Canadys", "Ritter"]),
])
def test_desc_endpoints(title, endpoints):
    e = desc.DescEntry(page=1, title=title, project_id="", description="", need="",
                       status="", in_service_text="10/1/2025 (phase 1) and 10/1/2026")
    assert e.endpoints == endpoints
    assert e.in_service == (date(2025, 10, 1), date(2026, 10, 1))


def test_gpc_rows_wrap_across_lines_and_pages():
    lines = [
        (180, "219 2026 20001 SAV: MCINTOSH - PURRYSBURG 6/1/2026 SAV REDACTED REDACTED"),
        (180, "230KV REACTORS"),
        (180, "2024 GA ITS Ten-Year Plan (2025-2034) Page 10 of 304"),
        (181, "PUBLIC DISCLOSURE"),
        (181, "TEAMS Need Date Project Estimated Cost - Estimated Cost -"),
        (181, "215 2033 17993 EVANS PRIMARY - THOMSON 12/31/2033 GPC REDACTED REDACTED"),
        (181, "PRIMARY 115KV REBUILD"),
        (181, "212 2025 18670 GTC: BANKS CROSSING - 5/1/2025 GTC REDACTED REDACTED"),
    ]
    rows = gpc_its.parse_lines(lines)
    assert [(r.name, r.sponsor, r.need) for r in rows] == [
        ("SAV: MCINTOSH - PURRYSBURG 230KV REACTORS", "SAV", date(2026, 6, 1)),
        ("EVANS PRIMARY - THOMSON PRIMARY 115KV REBUILD", "GPC", date(2033, 12, 31)),
        ("GTC: BANKS CROSSING -", "GTC", date(2025, 5, 1)),
    ]
    s = rows[1].as_sertp()
    assert s.endpoints == ["EVANS PRIMARY", "THOMSON PRIMARY"] and s.voltage_kv == 115


def test_planning_entity_groups_southern_companies():
    assert planning_entity("Georgia Power") == planning_entity("Southern Company ")
    assert planning_entity("Georgia Power") != planning_entity("Dominion Energy South Carolina")


def _norm(name: str) -> str:
    """Reference and filing titles differ in case, dashes, spacing and the 'SAV:' prefix."""
    text = re.sub(r"^[A-Za-z]+:\s*", "", name).lower().replace("–", "-")
    return re.sub(r"\s+", "", text)


@requires_db
def test_sperry_reference_overlaps_are_all_flagged():
    """Every overlap in Sperry's reference table is flagged from the committed DESC and
    Georgia Power snapshots, no farther apart than Sperry's centre-to-centre distance
    (we measure closest points, which can only be nearer)."""
    openpyxl = pytest.importorskip("openpyxl")
    wb = openpyxl.load_workbook(REFERENCE, data_only=True)
    names = {r[0]: r[3] for r in wb["projects"].iter_rows(min_row=2, values_only=True) if r[0]}
    reference = [r for r in wb["overlaps"].iter_rows(min_row=2, values_only=True) if r[0]]
    assert len(reference) == 6

    projects = [
        *snapshot.read_export(snapshot.EXTRACTED_DIR / snapshot.DESC.export),
        *snapshot.read_export(snapshot.EXTRACTED_DIR / snapshot.GPC_ITS.export),
    ]

    async def body(conn):
        await repo.insert_projects(conn, projects)
        return await matching.overlaps(conn, 40 / matching.KM_PER_MILE, 365)

    pairs = run_db(body)
    found = {}
    for p in pairs:
        key = frozenset((_norm(p.project_a.name), _norm(p.project_b.name)))
        found[key] = min(found.get(key, 1e9), p.miles)
    for ovl_id, miles, _gap, _ua, a, _na, _ub, b, _nb in reference:
        key = frozenset((_norm(names[a]), _norm(names[b])))
        assert key in found, f"{ovl_id} ({names[a]} / {names[b]}) not flagged"
        assert found[key] <= miles + 0.5, (ovl_id, found[key], miles)
