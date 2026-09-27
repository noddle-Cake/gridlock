"""Public-data loaders: SERTP page parser, OSM name matching, locating, EIA-860M rows."""

from __future__ import annotations

import csv

import pytest

from app.services.owners import canonical_utility
from app.sources import locate as locate_mod
from app.sources import substations
from app.sources.eia860m import PlannedPlant
from app.sources.sertp import parse_page_text
from app.sources.substations import Substation, name_key
from tests.conftest import DB_AVAILABLE, TEST_DATABASE_URL, run_db

PAGE = """In-Service 2027
Year:
Project Name: GTC: ADAMSVILLE - BUZZARD ROOST 230 KV REBUILD
Description: Rebuild about 5 miles of the Adamsville - Buzzard Roost 230 kV line with 200°C 1351
ACSS Martin.
Supporting The Adamsville - Buzzard Roost 230kV line overloads under contingency.
Statement:
In-Service 2031
Year:
Project Name: SOCO: REPLACE HURRICANE CREEK 230/115 KV AUTOBANK
Description: Replace the autobank.
Supporting The bank overloads under
Statement: contingency.
In-Service 2028
Year:
Project Name: LAWSONS FORK TIE - WEST SPARTANBURG TIE 100 KV TRANSMISSION LINES, INSTALL
RAS
Description: Install a remedial action scheme.
Supporting Overloads.
Statement:
06/12/2026 Page 27 of 115"""


def test_parse_page_text_reads_every_entry():
    gtc, soco, duke = (
        parse_page_text(PAGE, page=27, area="SOUTHERN")[:2]
        + parse_page_text(PAGE, page=2, area="DUKE CAROLINAS")[2:]
    )
    assert (gtc.year, gtc.page, gtc.owner, gtc.states) == (
        2027, 27, "Georgia Transmission Corp", ["GA"])
    assert gtc.endpoints == ["ADAMSVILLE", "BUZZARD ROOST"]
    assert gtc.voltage_kv == 230 and gtc.kind == "transmission line"
    assert "1351 ACSS Martin." in gtc.description

    assert soco.owner == "Southern Company" and soco.states == ["GA", "AL", "MS", "FL"]
    assert soco.endpoints == ["HURRICANE CREEK"] and soco.kind == "substation"
    assert soco.supporting == "The bank overloads under contingency."

    # Wrapped project names and the page footer don't leak into fields.
    assert duke.owner == "Duke Energy Carolinas"
    assert duke.endpoints == ["LAWSONS FORK TIE", "WEST SPARTANBURG TIE"]
    assert "Page 27" not in duke.supporting


@pytest.mark.parametrize("plan, osm", [
    ("LAWSONS FORK TIE", "Lawson's Fork Substation"),
    ("WINDER PRIMARY", "Winder Primary Substation"),
    ("SANDERSVILLE #1", "Sandersville Substation"),
    ("MT ZION", "Mount Zion Substation"),
    ("NELSON (BLACK)", "Nelson"),
])
def test_name_key_matches_plan_and_osm_spellings(plan, osm):
    assert name_key(plan) == name_key(osm)


@pytest.fixture
def fake_osm(monkeypatch):
    index = {
        "winder": [Substation("GA", "Winder Primary", "substation", "Georgia Power", 34.0, -83.7)],
        "doyle": [Substation("GA", "Doyle", "substation", "Georgia Power", 33.9, -83.9)],
        "oak grove": [  # two different places: ambiguous
            Substation("GA", "Oak Grove", "substation", "", 33.0, -84.0),
            Substation("GA", "Oak Grove", "substation", "", 31.0, -82.0),
        ],
    }
    monkeypatch.setattr(substations, "_index", lambda: index)
    return index


class FakePlaces:
    def __init__(self, data):
        self.data = data

    def places(self, name):
        return self.data.get(name.upper(), [])


def test_lookup_respects_state_and_ambiguity(fake_osm):
    assert substations.lookup("WINDER PRIMARY", ["GA"]).lat == 34.0
    assert substations.lookup("WINDER PRIMARY", ["AL"]) is None
    assert substations.lookup("OAK GROVE", ["GA"]) is None


def test_locate_line_between_two_osm_substations_is_exact(fake_osm):
    got = locate_mod.locate(["DOYLE", "WINDER PRIMARY"], ["GA"], FakePlaces({}))
    assert (got.lat, got.lng, got.approximate) == (33.95, -83.8, False)
    assert "midpoint" in got.how


def test_locate_falls_back_to_county_centre_marked_approximate(fake_osm, monkeypatch):
    monkeypatch.setattr(locate_mod, "county_centroid", lambda ref, st: [
        type("C", (), {"lat": 33.5, "lng": -85.0})()] if ref == "Carroll County" else [])
    places = FakePlaces({"BUZZARD ROOST": [
        {"state": "GA", "county": "Carroll County", "lat": 33.6, "lng": -85.1, "label": "x"}]})
    got = locate_mod.locate(["BUZZARD ROOST"], ["GA"], places)
    assert (got.lat, got.lng, got.approximate, got.requires_review) == (33.5, -85.0, True, False)


def test_locate_unresolved_needs_review(fake_osm):
    got = locate_mod.locate(["NOWHERE"], ["GA"], FakePlaces({}))
    assert got.lat is None and got.requires_review


def test_curated_overrides_pin_and_block_for_their_planning_entity(fake_osm, tmp_path,
                                                                   monkeypatch):
    path = tmp_path / "overrides.csv"
    path.write_text(
        "operator,name,state,county,lat,lng,approximate,source\n"
        "Georgia Power,Oak Grove,,,33.0,-84.0,false,picked from two same-named\n"
        "Georgia Power,Winder Primary,,,,,,wrong same-named feature\n"
        "Georgia Power,Doyle,GA,Fulton County,,,true,county\n"
    )
    table = locate_mod._overrides.__wrapped__(path)
    monkeypatch.setattr(locate_mod, "_overrides", lambda: table)

    def at(names, operator):
        return locate_mod.locate(names, ["GA"], FakePlaces({}), operator=operator)

    pinned = at(["OAK GROVE"], "Georgia Power")  # ambiguous in OSM, pinned by the override
    assert (pinned.lat, pinned.lng, pinned.approximate) == (33.0, -84.0, False)
    assert at(["WINDER PRIMARY"], "Georgia Power").requires_review  # blocked despite OSM
    county = at(["DOYLE"], "Georgia Power")
    assert county.approximate and "county centre, curated" in county.how
    # Georgia Power and Southern Company plan together, so the override covers both ...
    assert at(["WINDER PRIMARY"], "Southern Company").requires_review
    # ... but not other utilities, and not calls without an operator.
    assert at(["WINDER PRIMARY"], "Duke Energy Carolinas").lat == 34.0
    assert at(["WINDER PRIMARY"], None).lat == 34.0


def test_committed_overrides_all_resolve():
    table = locate_mod._overrides.__wrapped__(locate_mod.OVERRIDES_PATH)
    with locate_mod.OVERRIDES_PATH.open() as f:
        rows = list(csv.DictReader(f))
    assert len(table) == len(rows)  # one key per row, every county found
    assert all(r["source"].strip() for r in rows)  # every row says why
    assert locate_mod.override("Georgia Power", "BUZZARD ROOST").lat is None  # blocked


def test_eia_plant_record_cites_rows():
    plant = PlannedPlant(
        plant_id=1, plant_name="Dega Solar", entity="Tennessee Valley Authority", state="AL",
        county="Talladega", balancing_authority="SOCO", lat=33.5, lng=-86.1, year=2029,
        month=12, sheet_index=2, rows=[2029, 2030],
        generators=[
            {"id": "D1", "mw": 200, "technology": "Solar Photovoltaic", "status": "(L)"},
            {"id": "D2", "mw": 200, "technology": "Batteries", "status": "(L)"},
        ],
    )
    assert plant.utility == "TVA"
    assert plant.name == "Dega Solar (Batteries, Solar Photovoltaic, 400 MW)"
    assert "row(s) 2029, 2030" in plant.excerpt()


def test_owner_aliases_line_up_sertp_and_eia():
    assert canonical_utility("Duke Energy Progress - (NC)") == "Duke Energy Progress"
    assert canonical_utility("Tennessee Valley Authority") == canonical_utility("TVA") == "TVA"


def test_ambiguous_substation_resolved_by_other_endpoint(fake_osm):
    # Two "Oak Grove"s; the one near Doyle (33.9, -83.9) is picked, the far one isn't.
    got = locate_mod.locate(["DOYLE", "OAK GROVE"], ["GA"], FakePlaces({}))
    assert (got.lat, got.lng, got.approximate) == (33.45, -83.95, False)
    assert "nearest of 2" in got.how


def test_nearby_same_named_substations_become_one_approximate_area(fake_osm):
    fake_osm["twin"] = [
        Substation("GA", "Twin", "substation", "", 33.00, -84.00),
        Substation("GA", "Twin", "substation", "", 33.10, -84.00),  # ~7 miles apart
    ]
    got = locate_mod.locate(["TWIN"], ["GA"], FakePlaces({}))
    assert (got.lat, got.lng, got.approximate) == (33.05, -84.0, True)


@pytest.mark.parametrize("name, endpoints", [
    ("SOCO: ASHLEY PARK-WANSLEY 500 KV LINE", ["ASHLEY PARK", "WANSLEY"]),
    ("SOCO: REMOVE LIMITING ELEMENTS ON SOUTH COWETA 115 KV", ["SOUTH COWETA"]),
    ("SOCO: LINE CREEK TERMINAL EQUIPMENT REPLACEMENT", ["LINE CREEK"]),
    ("CAMPOBELLO TIE AND CAMPOBELLO TIE 100 KV", ["CAMPOBELLO TIE"]),
])
def test_endpoint_cleanup(name, endpoints):
    from app.sources.sertp import SertpEntry

    entry = SertpEntry(page=1, area="SOUTHERN", year=2027, name=name, description="",
                       supporting="")
    assert entry.endpoints == endpoints


@pytest.mark.parametrize("name, place", [
    ("HARRISBURG TIE 230/100/44 KV AUTOTRANSFORMER", "Harrisburg"),
    ("LAWSONS FORK TIE", "Lawsons Fork"),
    ("DURHAM MAIN", "Durham"),
    ("CUSTOMER DELIVERY", ""),
])
def test_place_name_strips_equipment_words(name, place):
    assert locate_mod.place_name(name) == place


def test_committed_snapshots_read_back_with_citations():
    from app.sources import region, snapshot

    eia = snapshot.read_export(snapshot.EXTRACTED_DIR / snapshot.EIA860M.export)
    grid = snapshot.read_export(snapshot.EXTRACTED_DIR / snapshot.SERTP.export)
    # Nationwide: 1,649 EIA plant/month sites (78 in SC/GA/FL) and all 426 SERTP projects.
    assert len(eia) == 1649 and len(grid) == 426
    assert sum(p.state in region.REGION_STATES for p in eia) == 78
    assert all(p.source_url and p.source_page and p.raw_excerpt for p in eia + grid)
    assert all(p.lat is not None for p in eia)
    assert all((p.lat is None) == p.requires_review for p in grid)
    assert snapshot.page_range(grid)


@pytest.mark.skipif(not DB_AVAILABLE, reason="no Postgres+PostGIS test database")
def test_startup_snapshot_load_is_idempotent_and_follows_csv_changes(tmp_path):
    import asyncpg

    from app.sources import snapshot

    def write(n: int) -> None:  # header + n projects per source (excerpts span lines)
        for source in snapshot.SOURCES:
            with (snapshot.EXTRACTED_DIR / source.export).open(newline="") as f:
                rows = list(csv.reader(f))[: n + 1]
            with (tmp_path / source.export).open("w", newline="") as f:
                csv.writer(f, lineterminator="\n").writerows(rows)

    async def load_twice_then_change(conn):
        pool = await asyncpg.create_pool(TEST_DATABASE_URL, min_size=1, max_size=2)
        counts = []
        try:
            for n in (3, 3, 5):  # same CSV twice (no duplicates), then a changed CSV
                write(n)
                await snapshot.load_snapshots(pool, tmp_path)
                counts.append((await conn.fetchval("SELECT count(*) FROM plans"),
                               await conn.fetchval("SELECT count(*) FROM projects")))
        finally:
            await pool.close()
        return counts

    k = len(snapshot.SOURCES)
    sizes = [len(snapshot.read_export(snapshot.EXTRACTED_DIR / s.export)) for s in snapshot.SOURCES]

    def rows(n: int) -> int:  # a small source (Tallahassee: 2 lines) has fewer than n
        return sum(min(n, size) for size in sizes)

    assert run_db(load_twice_then_change) == [(k, rows(3)), (k, rows(3)), (k, rows(5))]
