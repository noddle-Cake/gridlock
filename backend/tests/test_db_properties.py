"""DB-backed properties: run against a disposable Postgres+PostGIS database."""

from __future__ import annotations

import itertools
import math
from datetime import date, timedelta

from hypothesis import given, settings
from hypothesis import strategies as st

from app.db import repository as repo
from app.models.enums import DatePrecision, ProjectType
from app.services import matching
from tests.conftest import requires_db, run_db

pytestmark = requires_db

BASE = date(2025, 1, 1)
UTILITIES = ["Met-Ed", "BGE", "PPL", "met-ed "]  # "met-ed " is the same utility as "Met-Ed"


@st.composite
def new_projects(draw, utilities=UTILITIES):
    has_geom = draw(st.booleans() | st.just(True))
    start = draw(st.one_of(st.none(), st.integers(0, 1500)))
    length = draw(st.integers(0, 400))
    end = draw(st.one_of(st.none(), st.just(None if start is None else start + length),
                         st.integers(0, 1900)))
    if start is not None and end is not None and end < start:
        start, end = end, start
    return repo.NewProject(
        utility=draw(st.sampled_from(utilities)),
        confidence=draw(st.floats(0, 1)),
        name=draw(st.text(max_size=20)),
        type=draw(st.one_of(st.none(), st.sampled_from(list(ProjectType)))),
        voltage_kv=draw(st.one_of(st.none(), st.sampled_from([69, 115, 138, 230, 345, 500]))),
        lat=draw(st.floats(39.5, 40.5)) if has_geom else None,
        lng=draw(st.floats(-77.5, -76.5)) if has_geom else None,
        start_date=None if start is None else BASE + timedelta(days=start),
        end_date=None if end is None else BASE + timedelta(days=end),
    )


def _span(p) -> tuple[date, date] | None:
    s = p.start_date or p.end_date
    e = p.end_date or p.start_date
    return None if s is None else (s, e)


def _haversine_miles(a, b) -> float:
    r = 3958.7613
    p1, p2 = math.radians(a.lat), math.radians(b.lat)
    dp, dl = p2 - p1, math.radians(b.lng - a.lng)
    h = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(h))


def _qualifies(a, b, radius: float, slack: float) -> bool:
    """Distance alone decides membership; timing only ranks (dates may be missing)."""
    if a.lat is None or b.lat is None:
        return False
    if a.utility.strip().lower() == b.utility.strip().lower():
        return False
    return _haversine_miles(a, b) <= radius * slack


project_sets = st.lists(new_projects(), min_size=0, max_size=12)
radii = st.floats(0, 60)
pads = st.integers(0, 120)


# Feature: gridmerge, Property 1: Valid pair membership
@given(project_sets, radii, pads)
def test_valid_pair_membership(projects, radius, pad):
    async def body(conn):
        ids = await repo.insert_projects(conn, projects)
        return ids, await repo.candidate_pairs(conn, radius, pad)

    ids, rows = run_db(body)
    by_id = dict(zip(ids, projects, strict=True))
    found = set()
    for r in rows:
        a, b = by_id[r.a_id], by_id[r.b_id]
        assert r.a_id < r.b_id  # distinct ids, each unordered pair once
        assert a.utility.strip().lower() != b.utility.strip().lower()
        assert a.lat is not None and b.lat is not None
        assert 0 <= r.miles <= radius + 1e-6
        sa, sb = _span(a), _span(b)
        if sa is None or sb is None:
            # Undated: timing unknown, never a reason to drop the pair.
            assert r.time_gap_days is None and r.overlap_days == 0
            assert r.window_start is None and r.window_end is None
        else:
            assert r.time_gap_days == max((sa[0] - sb[1]).days, (sb[0] - sa[1]).days, 0)
            p = timedelta(days=pad)
            lo, hi = max(sa[0], sb[0]) - p, min(sa[1], sb[1]) + p
            if lo <= hi:
                assert r.overlap_days == (hi - lo).days + 1 >= 1
                assert (r.window_start, r.window_end) == (lo, hi)
            else:
                assert r.overlap_days == 0 and r.window_start is None and r.window_end is None
        found.add((r.a_id, r.b_id))

    # Completeness (sanity): pairs clearly inside the radius are never missed.
    for (ia, a), (ib, b) in itertools.combinations(sorted(by_id.items()), 2):
        if _qualifies(a, b, radius, slack=0.99):
            assert (ia, ib) in found


# Feature: gridmerge, Property 2: Matching symmetry and well-formed distance
@given(project_sets, radii, pads)
def test_matching_symmetry(projects, radius, pad):
    def pairs_for(order):
        async def body(conn):
            ids = await repo.insert_projects(conn, [projects[i] for i in order])
            logical = dict(zip(ids, order, strict=True))
            rows = await repo.candidate_pairs(conn, radius, pad)
            return {
                frozenset((logical[r.a_id], logical[r.b_id])): (r.miles, r.overlap_days)
                for r in rows
            }
        return body

    forward = run_db(pairs_for(list(range(len(projects)))))
    backward = run_db(pairs_for(list(reversed(range(len(projects))))))
    assert forward.keys() == backward.keys()
    for key, (miles, days) in forward.items():
        assert miles >= 0
        assert math.isclose(miles, backward[key][0], abs_tol=1e-6)
        assert days == backward[key][1]


# Feature: gridmerge, Property 13: Persistence round-trip
@given(new_projects(), st.sampled_from(list(DatePrecision)))
def test_persistence_round_trip(p, precision):
    p.start_precision = precision if p.start_date else None
    p.end_precision = precision if p.end_date else None
    p.source_url, p.source_page, p.raw_excerpt = "https://x.test/plan.pdf", 3, "excerpt"
    p.state, p.location_ref, p.approximate = "PA", "Adams County, PA", True

    async def body(conn):
        (pid,) = await repo.insert_projects(conn, [p])
        srid = await conn.fetchval(
            "SELECT ST_SRID(geom::geometry) FROM projects WHERE id = $1", pid
        )
        type_name = await conn.fetchval(
            "SELECT format_type(atttypid, atttypmod) FROM pg_attribute "
            "WHERE attrelid = 'projects'::regclass AND attname = 'geom'"
        )
        return await repo.get_project(conn, pid), srid, type_name

    got, srid, type_name = run_db(body)
    assert type_name == "geography(Point,4326)"
    assert got.utility == repo.clean(p.utility).strip()
    for f in ("state", "name", "type", "location_ref", "start_date", "end_date",
              "start_precision", "end_precision", "source_url", "source_page", "raw_excerpt",
              "reviewed", "approximate", "requires_review"):
        assert getattr(got, f) == repo.clean(getattr(p, f)), f
    assert got.voltage_kv == repo.round_voltage(p.voltage_kv)
    assert math.isclose(got.confidence, p.confidence, abs_tol=1e-6)
    if p.lat is None:
        assert got.lat is None and got.lng is None and srid is None
    else:
        assert srid == 4326
        assert math.isclose(got.lat, p.lat, abs_tol=1e-9)
        assert math.isclose(got.lng, p.lng, abs_tol=1e-9)


edits = st.fixed_dictionaries({}, optional={
    "lat": st.floats(39.5, 40.5),
    "start_offset": st.integers(0, 1500),
    "length": st.integers(0, 400),
    "name": st.text(max_size=10),
}).filter(bool)


# Feature: gridmerge, Property 14: Edit round-trip and effect on matching
@settings(max_examples=100)
@given(st.lists(new_projects(), min_size=2, max_size=10), st.data(), edits)
def test_edit_round_trip_and_rematch(projects, data, edit):
    target_index = data.draw(st.integers(0, len(projects) - 1))
    radius, pad = 25.0, 30

    async def body(conn):
        ids = await repo.insert_projects(conn, projects)
        target = ids[target_index]
        # Every currently flagged pair gets a brief (the stored Coordination_Pairs).
        before = await repo.candidate_pairs(conn, radius, pad)
        for r in before:
            await repo.upsert_brief(
                conn, pair_id=matching.pair_id(r.a_id, r.b_id), a_id=r.a_id, b_id=r.b_id,
                text="brief", miles=r.miles, overlap_days=r.overlap_days, radius=radius,
                pad=pad,
            )
        changes: dict = {}
        if "lat" in edit:
            changes["lat"], changes["lng"] = edit["lat"], -77.0
        if "start_offset" in edit:
            start = BASE + timedelta(days=edit["start_offset"])
            changes["start_date"] = start
            changes["end_date"] = start + timedelta(days=edit.get("length", 0))
        if "name" in edit:
            changes["name"] = edit["name"]
        updated = await repo.update_project(conn, target, changes)
        result = await matching.rematch_project(conn, target)
        after = {(r.a_id, r.b_id): r for r in await repo.candidate_pairs(conn, radius, pad)}
        briefs = {b.pair_id: b for b in await repo.briefs_for_project(conn, target)}
        return target, before, updated, result, after, briefs

    target, before, updated, result, after, briefs = run_db(body)

    if "name" in edit:
        assert updated.name == repo.clean(edit["name"])
    if "lat" in edit:
        assert math.isclose(updated.lat, edit["lat"], abs_tol=1e-9)
        assert updated.lng == -77.0
    if "start_offset" in edit:
        assert updated.start_date == BASE + timedelta(days=edit["start_offset"])

    # The re-match result is exactly the target's qualifying pairs under the new values.
    assert {(p.project_a.id, p.project_b.id) for p in result.pairs} == {
        k for k in after if target in k
    }
    for r in before:
        if target not in (r.a_id, r.b_id):
            continue
        pid = matching.pair_id(r.a_id, r.b_id)
        if (r.a_id, r.b_id) in after:
            # Still qualifies: kept, with facts matching the post-edit values.
            now = after[(r.a_id, r.b_id)]
            assert pid in briefs and pid not in result.invalidated
            assert math.isclose(briefs[pid].miles, now.miles, abs_tol=1e-6)
            assert briefs[pid].overlap_days == now.overlap_days
        else:
            # No longer qualifies: invalidated (removed).
            assert pid not in briefs and pid in result.invalidated


# Stretch 15.2: with 3+ utilities every distinct utility combination is evaluated.
@given(st.lists(st.sampled_from(["A", "B", "C", "D", "E"]), min_size=3, max_size=10))
def test_cross_utility_coverage(utilities):
    projects = [
        repo.NewProject(utility=u, confidence=1, lat=40.0, lng=-77.0,
                        start_date=date(2026, 1, 1), end_date=date(2026, 6, 30))
        for u in utilities
    ]
    rows = run_db(lambda conn: _insert_and_match(conn, projects))
    expected = sum(1 for a, b in itertools.combinations(utilities, 2) if a != b)
    assert len(rows) == expected
    combos = {frozenset((utilities[r.a_id - 1], utilities[r.b_id - 1])) for r in rows}
    assert combos == {frozenset(c) for c in itertools.combinations(set(utilities), 2)}


async def _insert_and_match(conn, projects):
    await repo.insert_projects(conn, projects)
    return await repo.candidate_pairs(conn, 1.0, 0)
