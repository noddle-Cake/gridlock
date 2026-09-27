"""Florida sources (FRCC Form 13, City of Tallahassee) and the planning region."""

from __future__ import annotations

import csv
from datetime import date

import pytest

from app.services.owners import canonical_utility
from app.sources import florida, region, snapshot


def _row(*cells: tuple[str, float]) -> list[dict]:
    """pdfplumber-style words: (text, x0); x1 from a fixed 6 pt per character."""
    return [{"text": t, "x0": x, "x1": x + 6 * len(t)} for t, x in cells]


def test_form13_rows_split_terminals_at_the_column_gap():
    rows = [
        _row(("OWNERSHIP", 32), ("TERMINALS", 229), ("CKT.", 424)),  # header: skipped
        _row(("DEF", 50), ("NOVA", 99), ("SUBSTATION", 126), ("SWEETWATER", 258),
             ("SUBSTATION", 324), ("1.0", 443), ("01/2028", 508), ("230", 588), ("919", 647),
             ("NA", 705)),
        _row(("DEF-SEC", 39), ("DEF", 99), ("MARTIN", 119), ("WEST", 155), ("SEC", 258),
             ("SILVER", 278), ("SPRINGS", 312), ("NORTH", 354), ("1.0", 443), ("3/2026", 511),
             ("230", 588), ("1195", 645), ("NA", 705)),
        _row(("FPL", 51), ("OASIS", 99), ("QUARRY", 257), ("15", 444), ("12/3033", 508),
             ("500", 588), ("3464", 645), ("NA", 705)),
        # Page 85 lays the columns out elsewhere and spaces the date.
        _row(("PEC", 95), ("SOUTHPORT", 164), ("HIGHPOINT", 273), ("7.3", 402), ("12", 470),
             ("/", 481), ("2026", 486), ("115", 555), ("217", 621), ("NA", 682)),
    ]
    nova, joint, oasis, pec = florida.parse_form13_rows(rows, page=62)

    assert (nova.owner, nova.endpoints) == ("Duke Energy Florida",
                                            ["NOVA SUBSTATION", "SWEETWATER SUBSTATION"])
    assert nova.title == "Nova - Sweetwater 230 kV Line"
    assert (nova.in_service, nova.voltage_kv, nova.miles) == (date(2028, 1, 1), 230, 1.0)
    # Joint line: both owners, and the owner codes that prefix each terminal are dropped.
    assert joint.owner == "Duke Energy Florida / Seminole Electric Cooperative"
    assert joint.endpoints == ["MARTIN WEST", "SILVER SPRINGS NORTH"]
    # "12/3033" is a typo for 2033, corrected and noted in the excerpt.
    assert oasis.in_service == date(2033, 12, 1) and "printed 12/3033" in oasis.excerpt()
    assert (pec.owner, pec.endpoints, pec.in_service) == (
        "PowerSouth", ["SOUTHPORT", "HIGHPOINT"], date(2026, 12, 1))


def test_tallahassee_table_rows():
    text = (
        "Reconductor / Rebuild Line 20A Sub 7 7507 Sub 16 7516 12/2030 115 3.03\n"
        "Reconductor / Rebuild Line 20B Sub 16 7516 Bradfordville W (DEF) 3105 12/2030 115 3.08"
    )
    a, b = florida.parse_tallahassee_text(text)
    assert a.owner == "City of Tallahassee" and a.endpoints == ["Sub 7", "Sub 16"]
    assert b.endpoints == ["Sub 16", "Bradfordville W"]
    assert (b.in_service, b.voltage_kv, b.miles) == (date(2030, 12, 1), 115, 3.08)
    assert "Line 20B" in b.excerpt()


def test_pec_is_powersouth():
    assert canonical_utility("PEC") == "PowerSouth"


@pytest.mark.parametrize(("lat", "lng", "state"), [
    (33.99, -81.03, "SC"),  # Columbia
    (33.75, -84.39, "GA"),  # Atlanta
    (30.44, -84.28, "FL"),  # Tallahassee
    (33.52, -86.80, "AL"),  # Birmingham
    (35.23, -80.84, "NC"),  # Charlotte
])
def test_state_at(lat, lng, state):
    assert region.state_at(lat, lng) == state


def test_region_keeps_southeast_projects_only():
    assert region.in_region(30.44, -84.28)
    assert not region.in_region(35.23, -80.84)
    # Unplaced: kept only when the owner operates in region states alone.
    assert region.in_region(None, None, ["GA"])
    assert not region.in_region(None, None, ["GA", "AL", "MS", "FL"])
    assert not region.in_region(None, None, [])


def _rows(source: snapshot.Source) -> list[dict]:
    with (snapshot.EXTRACTED_DIR / source.export).open() as f:
        return list(csv.DictReader(f))


def test_committed_snapshots_stay_in_the_region():
    """EIA-860M is cut by the plant's state and SERTP by where each project was located.
    The utilities' own filings (DESC, Georgia Power, Florida) are the region by definition;
    a border project such as Georgia Power's West Point Dam line may locate just across."""
    assert {r["state"] for r in _rows(snapshot.EIA860M)} <= set(region.REGION_STATES)
    for r in _rows(snapshot.SERTP):
        if r["lat"]:
            assert region.state_at(float(r["lat"]), float(r["lng"])) in region.REGION_STATES, (
                r["name"], r["lat"], r["lng"])
    florida_rows = _rows(snapshot.FRCC) + _rows(snapshot.TALLAHASSEE)
    assert len(florida_rows) == 25 and {r["state"] for r in florida_rows} == {"FL"}
