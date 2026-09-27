"""DB-backed properties: run against a disposable Postgres+PostGIS database."""

from __future__ import annotations

import itertools
import math
from datetime import date, timedelta

from hypothesis import given, settings
from hypothesis import strategies as st

from app.db import repository as repo
from app.models.enums import DatePrecision, ProjectType
from app.services import matching, timing
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


def _haversine_miles(a, b) -> float:
    r = 3958.7613
    p1, p2 = math.radians(a.lat), math.radians(b.lat)
    dp, dl = p2 - p1, math.radians(b.lng - a.lng)
    h = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(h))


def _in_time(a, b, rules: matching.Rules) -> bool:
    """Both still ahead of the cutoff and building together long enough (matching.qualifies)."""
    wa = timing.build_window(a.start_date, a.end_date)
    wb = timing.build_window(b.start_date, b.end_date)
    if wa is None or wb is None or min(wa.end, wb.end) < rules.planning_from:
        return False
    remaining = (min(wa.end, wb.end) - max(wa.start, wb.start, rules.planning_from)).days + 1
    return remaining >= rules.min_overlap_days


def _qualifies(a, b, radius: float, slack: float, rules: matching.Rules) -> bool:
    """A match is close in space (within the radius) and in time (_in_time)."""
    if a.lat is None or b.lat is None:
        return False
    if a.utility.strip().lower() == b.utility.strip().lower():
        return False
    return _haversine_miles(a, b) <= radius * slack and _in_time(a, b, rules)


project_sets = st.lists(new_projects(), min_size=0, max_size=12)
radii = st.floats(0, 60)


# Feature: gridmerge, Property 1: Valid pair membership
@given(project_sets, radii)
def test_valid_pair_membership(projects, radius):
    async def body(conn):
        ids = await repo.insert_projects(conn, projects)
        return ids, await matching.overlaps(conn, radius)

    ids, pairs = run_db(body)
    rules = matching.Rules.current()  # PLANNING_FROM is pinned by conftest
    by_id = dict(zip(ids, projects, strict=True))
    found = set()
    for pair in pairs:
        ia, ib = pair.project_a.id, pair.project_b.id
        a, b = by_id[ia], by_id[ib]
        assert ia < ib  # distinct ids, each unordered pair once
        assert a.utility.strip().lower() != b.utility.strip().lower()
        assert a.lat is not None and b.lat is not None
        assert 0 <= pair.miles <= radius + 1e-3
        # Close in time: dated, still ahead, building together long enough.
        assert _in_time(a, b, rules)
        # Timing comes from the stored dates alone.
        t = timing.compare(timing.build_window(a.start_date, a.end_date),
                           timing.build_window(b.start_date, b.end_date))
        assert pair.overlap_ratio == round(t.ratio, 4)
        assert pair.overlap_days == t.overlap_days >= rules.min_overlap_days
        assert pair.time_gap_days == t.in_service_gap_days
        assert pair.window_start == t.shared.start
        found.add((ia, ib))

    # Completeness (sanity): pairs clearly inside the radius and close in time are never missed.
    for (ia, a), (ib, b) in itertools.combinations(sorted(by_id.items()), 2):
        if _qualifies(a, b, radius, slack=0.99, rules=rules):
            assert (ia, ib) in found


# Feature: gridmerge, Property 2: Matching symmetry and well-formed distance
@given(project_sets, radii)
def test_matching_symmetry(projects, radius):
    def pairs_for(order):
        async def body(conn):
            ids = await repo.insert_projects(conn, [projects[i] for i in order])
            logical = dict(zip(ids, order, strict=True))
            pairs = await matching.overlaps(conn, radius)
            return {
                frozenset((logical[p.project_a.id], logical[p.project_b.id])):
                    (p.miles, p.overlap_days, p.overlap_ratio)
                for p in pairs
            }
        return body

    forward = run_db(pairs_for(list(range(len(projects)))))
    backward = run_db(pairs_for(list(reversed(range(len(projects))))))
    assert forward.keys() == backward.keys()
    for key, (miles, days, ratio) in forward.items():
        assert miles >= 0
        assert math.isclose(miles, backward[key][0], abs_tol=1e-3)
        assert (days, ratio) == backward[key][1:]


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
    radius = 25.0

    async def body(conn):
        ids = await repo.insert_projects(conn, projects)
        target = ids[target_index]
        # Every currently flagged pair gets a brief (the stored Coordination_Pairs).
        before = await matching.overlaps(conn, radius)
        for p in before:
            await repo.upsert_brief(
                conn, pair_id=p.id, a_id=p.project_a.id, b_id=p.project_b.id,
                text="brief", miles=p.miles, overlap_days=p.overlap_days, radius=radius,
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
        after = {
            (p.project_a.id, p.project_b.id): p for p in await matching.overlaps(conn, radius)
        }
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
    for p in before:
        key = (p.project_a.id, p.project_b.id)
        if target not in key:
            continue
        pid = p.id
        if key in after:
            # Still qualifies: kept, with facts matching the post-edit values.
            now = after[key]
            assert pid in briefs and pid not in result.invalidated
            assert math.isclose(briefs[pid].miles, now.miles, abs_tol=1e-3)
            assert briefs[pid].overlap_days == now.overlap_days
        else:
            # No longer qualifies: invalidated (removed).
            assert pid not in briefs and pid in result.invalidated


# Briefs flagged under different radii are each re-checked under their own radius, exactly
# as a per-brief find_pair would.
@settings(max_examples=50)
@given(st.lists(new_projects(), min_size=2, max_size=10), st.data())
def test_rematch_rechecks_each_brief_at_its_radius(projects, data):
    async def body(conn):
        ids = await repo.insert_projects(conn, projects)
        target = ids[data.draw(st.integers(0, len(ids) - 1))]
        for p in await matching.overlaps(conn, 25.0):
            await repo.upsert_brief(
                conn, pair_id=p.id, a_id=p.project_a.id, b_id=p.project_b.id,
                text="brief", miles=p.miles, overlap_days=p.overlap_days,
                radius=data.draw(st.floats(0.0, 25.0)),
            )
        expected = {}
        for b in await repo.briefs_for_project(conn, target):
            expected[b.pair_id] = await matching.find_pair(conn, b.a_id, b.b_id, b.radius)
        result = await matching.rematch_project(conn, target)
        return expected, result

    expected, result = run_db(body)
    assert set(result.invalidated) == {pid for pid, pair in expected.items() if pair is None}
    assert not set(result.updated) & set(result.invalidated)


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
    return await repo.candidate_pairs(conn, 1.0)


# Sperry: "measure the closest points between two projects, not their centers".
def test_line_route_measured_at_closest_point():
    # A ~60 km east-west line; its midpoint is ~30 km from a substation that sits 2 km
    # north of the line's western end.
    line = repo.NewProject(utility="A", confidence=1, lat=33.0, lng=-81.68,
                           route=[(33.0, -82.0), (33.0, -81.36)])
    sub = repo.NewProject(utility="B", confidence=1, lat=33.018, lng=-81.99)
    crossing = repo.NewProject(utility="C", confidence=1, lat=33.0, lng=-81.5,
                               route=[(32.9, -81.5), (33.1, -81.5)])

    async def body(conn):
        ids = await repo.insert_projects(conn, [line, sub, crossing])
        got = await repo.get_project(conn, ids[0])
        return got, {(r.a_id, r.b_id): r.miles for r in
                     await repo.candidate_pairs(conn, 40 / matching.KM_PER_MILE)}

    got, pairs = run_db(body)
    assert got.route == [(33.0, -82.0), (33.0, -81.36)]
    assert 1.8 < pairs[(1, 2)] * matching.KM_PER_MILE < 2.3  # not the ~30 km to the midpoint
    assert pairs[(1, 3)] < 1e-6 and matching.distance_band(pairs[(1, 3)]) == "touching"
    assert (2, 3) not in pairs  # ~46 km apart


def test_rematch_rechecks_briefs_on_routes_not_midpoints():
    # Crossing lines whose midpoints are ~30 km apart: 0 km as matched, so an edit that
    # doesn't move them must keep the brief as-is (not refresh it to the midpoint distance).
    when = {"start_date": date(2026, 3, 1), "end_date": date(2026, 12, 31)}  # a match in time
    a = repo.NewProject(utility="JEA", confidence=1, lat=33.0, lng=-81.72,
                        route=[(33.0, -82.0), (33.0, -81.44)], **when)
    b = repo.NewProject(utility="FPL", confidence=1, lat=33.13, lng=-81.5,
                        route=[(32.9, -81.5), (33.36, -81.5)], **when)

    async def body(conn):
        ids = await repo.insert_projects(conn, [a, b])
        (row,) = await repo.candidate_pairs(conn, 25.0)
        (pair,) = await matching.overlaps(conn, 25.0)
        await repo.upsert_brief(conn, pair_id=matching.pair_id(*ids), a_id=ids[0],
                                b_id=ids[1], text="brief", miles=row.miles,
                                overlap_days=pair.overlap_days, radius=25.0)
        await repo.update_project(conn, ids[0], {"name": "renamed"})
        return row, await matching.rematch_project(conn, ids[0])

    row, result = run_db(body)
    assert row.miles < 1e-6
    assert result.invalidated == [] and result.updated == []


def test_hand_placed_point_drops_route():
    line = repo.NewProject(utility="A", confidence=1, lat=33.0, lng=-81.68,
                           route=[(33.0, -82.0), (33.0, -81.36)])

    async def body(conn):
        (pid,) = await repo.insert_projects(conn, [line])
        return await repo.update_project(conn, pid, {"lat": 33.2, "lng": -81.7})

    assert run_db(body).route is None
