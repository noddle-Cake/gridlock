"""Public-data loaders: SERTP page parser, OSM name matching, locating, EIA-860M rows."""

from __future__ import annotations

import pytest

from app.services.owners import canonical_utility
from app.sources import locate as locate_mod
from app.sources import substations
from app.sources.eia860m import PlannedPlant
from app.sources.sertp import parse_page_text
from app.sources.substations import Substation, name_key

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
