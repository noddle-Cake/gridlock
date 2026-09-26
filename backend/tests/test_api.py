"""Endpoint contract tests (FastAPI TestClient against the Postgres+PostGIS test DB)."""

from __future__ import annotations

import time
from datetime import date

import pytest
from hypothesis import given
from hypothesis import strategies as st

from app.core.config import get_settings
from app.db import repository as repo
from app.models.enums import ProjectType
from app.services import matching
from app.services.geocoding import Candidate
from tests.test_ingestion import CSV, PNG

SRC = "https://example.com/plan.pdf"


def seed(projects: list[repo.NewProject]) -> list[int]:
    return run_db_keep(lambda conn: repo.insert_projects(conn, projects))


def run_db_keep(fn):
    """Like run_db but without wiping the database first."""
    from tests import conftest

    conftest.run_db(lambda conn: _noop())  # ensure the shared connection exists
    return conftest._runner.run(fn(conftest._conn))


async def _noop():
    return None


def two_nearby() -> list[repo.NewProject]:
    return [
        repo.NewProject(utility="Met-Ed", name="Hanover breakers", type=ProjectType.SUBSTATION,
                        voltage_kv=138, lat=39.80, lng=-76.98, confidence=0.9,
                        start_date=date(2026, 4, 1), end_date=date(2026, 6, 30),
                        source_url=SRC, source_page=4),
        repo.NewProject(utility="BGE", name="Westminster breakers", type=ProjectType.SUBSTATION,
                        voltage_kv=115, lat=39.58, lng=-77.00, confidence=0.5,
                        start_date=date(2026, 5, 1), end_date=date(2026, 9, 30),
                        source_url=SRC, source_page=2),
    ]


def count(table: str) -> int:
    return run_db_keep(lambda conn: conn.fetchval(f"SELECT count(*) FROM {table}"))


# ---------------------------------------------------------------- POST /ingest


def post_ingest(client, data=CSV, filename="plan.csv", utility="Met-Ed", source_url=SRC):
    form = {}
    if utility is not None:
        form["utility"] = utility
    if source_url is not None:
        form["source_url"] = source_url
    return client.post("/ingest", data=form, files={"file": (filename, data)})


def test_ingest_happy_path(api_client):
    api_client.llm.projects = [{
        "name": "Hanover breakers", "type": "substation", "voltage_kv": 138,
        "location_ref": "Adams County, PA", "location_kind": "county", "state": "PA",
        "start_date": "Q2 2026", "end_date": "Q4 2026", "source_page": 1,
        "raw_excerpt": "Hanover breakers", "certainty": 0.9,
    }]
    r = post_ingest(api_client)
    assert r.status_code == 202
    body = r.json()
    assert body["status"] == "processing" and body["plan_id"]
    assert body["utility"] == "Met-Ed" and body["source_url"] == SRC
    assert body["utility_stored"] and body["source_url_stored"]

    plan = api_client.get(f"/plans/{body['plan_id']}").json()
    assert plan["status"] == "complete" and plan["project_count"] == 1
    (p,) = api_client.get("/projects").json()
    assert p["reviewed"] is False and p["approximate"] is True
    assert p["start_date"] == "2026-04-01" and p["end_date"] == "2026-12-31"
    assert p["start_precision"] == "quarter" and p["source_url"] == SRC


@pytest.mark.parametrize(
    ("kwargs", "status", "code", "check"),
    [
        ({"utility": None}, 422, "missing_metadata", lambda e: e["field"] == "utility"),
        ({"source_url": ""}, 422, "missing_metadata", lambda e: e["field"] == "source_url"),
        ({"utility": None, "source_url": None}, 422, "missing_metadata",
         lambda e: e["fields"] == ["utility", "source_url"]),
        ({"data": PNG, "filename": "plan.pdf"}, 415, "unsupported_format",
         lambda e: e["detected_format"] == "png"),
        ({"data": b"%PDF-1.4 garbage", "filename": "x.pdf"}, 422, "unreadable_file",
         lambda e: "could not be read" in e["message"]),
    ],
)
def test_ingest_rejections_leave_no_record(api_client, kwargs, status, code, check):
    r = post_ingest(api_client, **kwargs)
    assert r.status_code == status
    err = r.json()["error"]
    assert err["code"] == code and check(err)
    assert count("plans") == 0 and count("projects") == 0


def test_ingest_oversize(api_client):
    settings = get_settings()
    settings.max_upload_bytes = 10
    r = post_ingest(api_client)
    assert r.status_code == 413 and "maximum size limit" in r.json()["error"]["message"]
    assert count("plans") == 0


def test_extraction_failure_creates_no_projects(api_client):
    api_client.llm.fail = True
    r = post_ingest(api_client)
    assert r.status_code == 202
    plan = api_client.get(f"/plans/{r.json()['plan_id']}").json()
    assert plan["status"] == "failed" and "Extraction failed" in plan["error"]
    assert count("projects") == 0


def test_utility_count_boundaries(api_client):
    async def add_plans(conn, n):
        for i in range(n):
            await repo.insert_plan(conn, utility=f"U{i}", source_url=SRC, filename=None,
                                   detected_format="csv")

    run_db_keep(lambda conn: add_plans(conn, 49))
    assert post_ingest(api_client, utility="Fiftieth").status_code == 202  # 50 is fine
    assert post_ingest(api_client, utility="U3").status_code == 202  # existing utility
    r = post_ingest(api_client, utility="Fifty-first")
    assert r.status_code == 422 and r.json()["error"]["code"] == "too_many_utilities"


# ---------------------------------------------------------------- GET /overlaps


def test_overlaps_defaults_and_scores(api_client):
    seed(two_nearby())
    body = api_client.get("/overlaps").json()
    assert body["radius"] == 25 and "pad" not in body
    (pair,) = body["pairs"]
    assert pair["id"] == "1-2"
    assert 14 < pair["miles"] < 17
    # Apr 1-Jun 30 vs May 1-Sep 30: 61 shared days of 183 either is building.
    assert (pair["window_start"], pair["window_end"]) == ("2026-05-01", "2026-06-30")
    assert pair["overlap_days"] == 61
    assert pair["overlap_ratio"] == pytest.approx(61 / 183, abs=1e-4)
    assert pair["scores"]["overlap"] == pytest.approx(61 / 183, abs=1e-4)
    assert pair["time_gap_days"] == 92  # Jun 30 -> Sep 30 in-service
    assert set(pair["scores"]) >= {"distance", "overlap", "type_similarity",
                                   "voltage_similarity", "composite", "indeterminate_factors"}
    assert pair["brief"] is None
    # Embedded projects skip the source excerpt (Review reads it from /projects).
    assert "raw_excerpt" not in pair["project_a"] and "raw_excerpt" not in pair["project_b"]
    assert pair["project_a"]["utility"] and "lat" in pair["project_b"]
    assert api_client.get("/overlaps?radius=5").json()["pairs"] == []


def test_distant_schedules_still_flagged(api_client):
    """Geography is primary: years between in-service dates rank a pair lower, never hide it
    (the Sperry reference Hooks–Thurmond / Evans–Thurmond pair is 3,074 days apart)."""
    near, far = two_nearby()
    far.start_date, far.end_date = date(2034, 12, 31), date(2034, 12, 31)
    undated = repo.NewProject(utility="PPL", name="Undated", lat=39.7, lng=-77.0,
                              confidence=0.9)
    seed([near, far, undated])
    pairs = {p["id"]: p for p in api_client.get("/overlaps").json()["pairs"]}
    assert set(pairs) == {"1-2", "1-3", "2-3"}
    gap = pairs["1-2"]
    assert gap["time_gap_days"] == (date(2034, 12, 31) - date(2026, 6, 30)).days
    assert gap["overlap_days"] == 0 and gap["window_start"] is None
    assert gap["overlap_ratio"] == 0 and gap["scores"]["overlap"] == 0
    assert pairs["1-3"]["time_gap_days"] is None and pairs["1-3"]["overlap_ratio"] is None
    assert "overlap" in pairs["1-3"]["scores"]["indeterminate_factors"]


def test_padding_no_longer_changes_scores(api_client):
    seed(two_nearby())
    plain = api_client.get("/overlaps").json()["pairs"]
    assert api_client.get("/overlaps?pad=900").json()["pairs"] == plain  # ignored if sent


@pytest.mark.parametrize("query", ["radius=-1", "radius=abc", "radius=inf"])
def test_overlaps_invalid_params(api_client, query):
    r = api_client.get(f"/overlaps?{query}")
    assert r.status_code == 422
    assert r.json()["error"]["fields"] == ["radius"]


@pytest.mark.parametrize(
    ("km", "band"),
    [(0, "touching"), (0.0005, "touching"), (0.5, "1.6"), (1.6, "8"), (7.99, "8"),
     (8, "25"), (24.9, "25"), (25, "40"), (39.9, "40"), (40, None), (60, None)],
)
def test_distance_band_edges_do_not_overlap(km, band):
    assert matching.distance_band(km / matching.KM_PER_MILE) == band


def test_overlaps_bands_filter(api_client):
    seed(two_nearby())
    radius = 40 / matching.KM_PER_MILE

    def get(query: str) -> list[dict]:
        return api_client.get(f"/overlaps?radius={radius}&{query}").json()["pairs"]

    (pair,) = get("bands=touching,1.6,8,25,40")
    assert 8 <= pair["miles"] * matching.KM_PER_MILE < 25  # ~24.5 km: the 8-25 km band
    assert [p["id"] for p in get("bands=25")] == ["1-2"]
    assert [p["id"] for p in get("bands=touching,25,40")] == ["1-2"]
    assert get("bands=touching,1.6,8,40") == []
    assert get("bands=") == []
    csv = api_client.get(f"/export?format=csv&radius={radius}&bands=40").text
    assert len(csv.strip().splitlines()) == 1  # header only


def test_overlaps_unknown_band(api_client):
    r = api_client.get("/overlaps?bands=8,100")
    assert r.status_code == 422
    assert r.json()["error"]["fields"] == ["bands"]


# ---------------------------------------------------------------- PATCH /projects/{id}


def test_patch_valid_edit_and_reviewed(api_client):
    seed(two_nearby())
    t0 = time.perf_counter()
    r = api_client.patch("/projects/2", json={"name": "Renamed", "reviewed": True,
                                              "voltage_kv": 230})
    assert time.perf_counter() - t0 < 2.0  # Req 13.2 latency budget
    assert r.status_code == 200
    p = r.json()
    assert p["name"] == "Renamed" and p["reviewed"] is True and p["voltage_kv"] == 230
    assert api_client.get("/projects").json()[0]["reviewed"] is True  # persisted (BGE sorts 1st)


def test_patch_not_found(api_client):
    r = api_client.patch("/projects/999", json={"reviewed": True})
    assert r.status_code == 404 and r.json()["error"]["code"] == "project_not_found"


def test_patch_geom_edit_invalidates_brief(api_client):
    seed(two_nearby())
    assert api_client.post("/overlaps/1-2/brief").status_code == 200
    assert api_client.get("/overlaps").json()["pairs"][0]["brief"]["stale"] is False

    # Move project 2 a little: still paired, brief facts refreshed and marked stale.
    api_client.patch("/projects/2", json={"lat": 39.70, "lng": -77.0})
    pair = api_client.get("/overlaps").json()["pairs"][0]
    assert pair["brief"]["stale"] is True

    # Move it far away: the pair no longer qualifies and the brief is invalidated.
    api_client.patch("/projects/2", json={"lat": 41.5, "lng": -75.0})
    assert api_client.get("/overlaps").json()["pairs"] == []
    api_client.patch("/projects/2", json={"lat": 39.70, "lng": -77.0})
    assert api_client.get("/overlaps").json()["pairs"][0]["brief"] is None


invalid_values = st.sampled_from([
    {"voltage_kv": 0}, {"voltage_kv": 5000}, {"voltage_kv": "high"},
    {"confidence": 1.5}, {"confidence": -0.1}, {"type": "battery"},
    # A lone coordinate is invalid; lng (not lat) so it never completes {"lat": 95, ...}
    # into a valid pair when merged.
    {"lat": 95, "lng": 0}, {"lng": 10}, {"start_date": "not-a-date"},
    {"source_page": 0}, {"raw_excerpt": "x" * 2001}, {"bogus_field": 1},
    {"utility": ""}, {"reviewed": None}, {"start_date": "2030-01-01", "end_date": "2029-01-01"},
])
valid_values = st.sampled_from([{"name": "Changed"}, {"reviewed": True}, {"state": "MD"}])


# Feature: gridmerge, Property 15: Invalid edits are rejected and leave the target unchanged
@given(st.lists(invalid_values, min_size=1, max_size=3), st.lists(valid_values, max_size=2))
def test_invalid_edits_rejected_unchanged(api_client, bad, good):
    if count("projects") == 0:
        seed(two_nearby())
    before = api_client.get("/projects").json()
    body: dict = {}
    for d in [*good, *bad]:
        body.update(d)
    r = api_client.patch("/projects/1", json=body)
    assert r.status_code == 422
    err = r.json()["error"]
    assert err["code"] == "invalid_fields"
    assert set(err["fields"]) & set(body)  # names at least one offending field
    assert set(err["fields"]) <= set(body) | {"body", "lat", "lng"}
    assert api_client.get("/projects").json() == before


# ---------------------------------------------------------------- POST /overlaps/{id}/brief


def test_brief_not_found(api_client):
    seed(two_nearby())
    for pid in ("1-3", "2-1", "junk"):
        r = api_client.post(f"/overlaps/{pid}/brief")
        assert r.status_code == 404 and r.json()["error"]["code"] == "pair_not_found"
    assert count("briefs") == 0


def test_brief_success(api_client):
    seed(two_nearby())
    r = api_client.post("/overlaps/1-2/brief")
    assert r.status_code == 200
    body = r.json()
    assert body["pair_id"] == "1-2" and len(body["text"]) <= 600
    assert "substation" in body["text"]
    assert api_client.get("/overlaps").json()["pairs"][0]["brief"]["text"] == body["text"]


def test_brief_timeout_and_failure_leave_pair_unchanged(api_client):
    seed(two_nearby())
    before = api_client.get("/overlaps").json()
    api_client.app_state.brief_generator._timeout = 0.05
    api_client.llm.delay = 0.5
    r = api_client.post("/overlaps/1-2/brief")
    assert r.status_code == 504 and r.json()["error"]["code"] == "brief_timeout"

    api_client.llm.delay = 0
    api_client.llm.fail = True
    r = api_client.post("/overlaps/1-2/brief")
    assert r.status_code == 502 and "model unavailable" in r.json()["error"]["message"]
    assert api_client.get("/overlaps").json() == before
    assert count("briefs") == 0


# ---------------------------------------------------------------- GET /export (Stretch)


def test_export_csv_and_pdf(api_client):
    seed(two_nearby())
    api_client.post("/overlaps/1-2/brief")
    r = api_client.get("/export?format=csv")
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/csv")
    lines = r.text.strip().splitlines()
    assert lines[0].startswith("pair_id,utility_a,project_a")
    assert "Met-Ed" in lines[1] and "BGE" in lines[1]
    assert ",2026-05-01,2026-06-30,61,33," in lines[1]  # shared window, days, overlap %
    r = api_client.get("/export?format=pdf")
    assert r.status_code == 200 and r.content.startswith(b"%PDF")
    assert api_client.get("/export?format=docx").status_code == 422


def test_geocoder_used_for_town_refs(api_client):
    api_client.geocoder.table["Hanover, PA"] = [Candidate(39.8, -76.98)]
    api_client.llm.projects = [{"name": "X", "location_ref": "Hanover, PA",
                                "location_kind": "town", "certainty": 1}]
    post_ingest(api_client)
    (p,) = api_client.get("/projects").json()
    assert (p["lat"], p["lng"]) == (39.8, -76.98) and p["approximate"] is False


def test_ingest_page_range_is_validated_and_recorded(api_client):
    bad = api_client.post("/ingest", data={"utility": "Met-Ed", "source_url": SRC, "pages": "2"},
                          files={"file": ("plan.csv", CSV)})
    assert bad.status_code == 422 and bad.json()["error"]["field"] == "pages"
    assert api_client.get("/plans").json() == []  # nothing persisted

    ok = api_client.post("/ingest", data={"utility": "Met-Ed", "source_url": SRC, "pages": "1"},
                         files={"file": ("plan.csv", CSV)})
    assert ok.status_code == 202
    assert api_client.get(f"/plans/{ok.json()['plan_id']}").json()["page_range"] == "1"
