"""Matching_Engine: PostGIS candidate query + Python scoring (Req 6, 7, 13.4)."""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date

import asyncpg

from app.core.config import get_settings
from app.core.errors import InvalidParameterError
from app.db import repository as repo
from app.models.dto import CoordinationPairDTO, ProjectDTO
from app.services import timing
from app.services.impact import estimate
from app.services.owners import planning_entity
from app.services.scoring import score_pair


def pair_id(a_id: int, b_id: int) -> str:
    lo, hi = sorted((a_id, b_id))
    return f"{lo}-{hi}"


def parse_pair_id(value: str) -> tuple[int, int] | None:
    parts = value.split("-")
    if len(parts) != 2 or not all(p.isdigit() for p in parts):
        return None
    a, b = int(parts[0]), int(parts[1])
    if a >= b:
        return None
    return a, b


def parse_radius(radius: str | None) -> float:
    """Validate the radius query param (Req 6.5-6.7)."""
    if radius is None or radius.strip() == "":
        return get_settings().default_radius_miles
    try:
        value = float(radius)
    except ValueError:
        reason = f"radius must be numeric (got {radius!r})"
    else:
        if not math.isfinite(value):
            reason = f"radius must be a finite number (got {radius!r})"
        elif value < 0:
            reason = f"radius must not be negative (got {radius!r})"
        else:
            return value
    raise InvalidParameterError(reason, fields=["radius"], field="radius")


# Distance bands the UI filters on, keyed by upper bound in km. They never overlap: each pair
# falls in exactly one band. Projects are points, so "touching" means the same location.
KM_PER_MILE = repo.METERS_PER_MILE / 1000
TOUCHING_KM = 0.001  # within a metre counts as the same spot
DISTANCE_BANDS_KM: dict[str, float] = {"touching": TOUCHING_KM, "1.6": 1.6, "8": 8.0,
                                       "25": 25.0, "40": 40.0}


def distance_band(miles: float) -> str | None:
    """The one band a pair's distance falls in, or None when it is 40 km or more."""
    km = miles * KM_PER_MILE
    if km <= TOUCHING_KM:
        return "touching"
    for band, upper in DISTANCE_BANDS_KM.items():
        if band != "touching" and km < upper:
            return band
    return None


# Sperry's ranking tiers: closer overlaps are worth more. The 8-25 and 25-40 km filter bands
# are one tier ("under 40 km -> can share crews and equipment").
TIERS: dict[str, int] = {"touching": 0, "1.6": 1, "8": 2, "25": 3, "40": 3}
OUTSIDE_TIER = len(set(TIERS.values()))


def tier(band: str | None) -> int:
    return TIERS.get(band, OUTSIDE_TIER) if band else OUTSIDE_TIER


def rank_key(pair: CoordinationPairDTO) -> tuple[int, float, float]:
    """Tier first, then the composite score (which carries timing), then distance."""
    return (tier(pair.band), -pair.scores.composite, pair.miles)


def parse_bands(raw: str | None) -> set[str] | None:
    """None when the param is absent (no band filter); an empty set when it is empty."""
    if raw is None:
        return None
    bands = {b.strip() for b in raw.split(",") if b.strip()}
    unknown = sorted(bands - DISTANCE_BANDS_KM.keys())
    if unknown:
        raise InvalidParameterError(
            f"bands must be drawn from {', '.join(DISTANCE_BANDS_KM)} (got {', '.join(unknown)})",
            field="bands", fields=["bands"],
        )
    return bands


def _cross_entity(
    rows: list[repo.CandidateRow], projects: dict[int, ProjectDTO]
) -> list[repo.CandidateRow]:
    """Drop pairs whose utilities plan together (owners.PLANNING_ENTITY)."""
    return [r for r in rows if planning_entity(projects[r.a_id].utility)
            != planning_entity(projects[r.b_id].utility)]


def _window(p: ProjectDTO) -> timing.Window | None:
    return timing.build_window(p.start_date, p.end_date, p.start_precision, p.end_precision)


@dataclass(frozen=True)
class Rules:
    """When a pair close in space is also close in time, and so a match."""

    planning_from: date  # both projects must still be in service on or after this date
    min_overlap_days: int  # and building together for at least this long

    @classmethod
    def current(cls) -> Rules:
        s = get_settings()
        return cls(planning_from=s.planning_cutoff, min_overlap_days=max(1, s.min_overlap_days))


def is_past(p: ProjectDTO, cutoff: date) -> bool:
    """In service before `cutoff` (its whole in-service period is behind it): finished work,
    nothing left to coordinate. Undated projects are not known to be past."""
    w = _window(p)
    return w is not None and w.end < cutoff


def _ahead(p: ProjectDTO, rules: Rules) -> bool:
    """Dated and not past: only such projects can be shown to build at the same time."""
    w = _window(p)
    return w is not None and w.end >= rules.planning_from


def qualifies(pair: CoordinationPairDTO, rules: Rules) -> bool:
    """Close in time as well as space: both projects still ahead and their build windows
    sharing at least `min_overlap_days`. Years apart, finished, or undated -> not a match."""
    return (_ahead(pair.project_a, rules) and _ahead(pair.project_b, rules)
            and pair.overlap_days >= rules.min_overlap_days)


def _current(
    rows: list[repo.CandidateRow], projects: dict[int, ProjectDTO], rules: Rules
) -> list[repo.CandidateRow]:
    """Candidates whose two projects are still ahead, before building their pair records."""
    return [r for r in rows if _ahead(projects[r.a_id], rules) and _ahead(projects[r.b_id], rules)]


def _build_pair(
    row: repo.CandidateRow, projects: dict[int, ProjectDTO], radius: float
) -> CoordinationPairDTO:
    a, b = projects[row.a_id], projects[row.b_id]
    wa, wb = _window(a), _window(b)
    # Undated projects: timing is unknown (factor flagged indeterminate), not "no overlap".
    t = timing.compare(wa, wb) if wa and wb else None
    scores = score_pair(
        miles=row.miles, overlap_ratio=t.ratio if t else None,
        type_a=a.type.value if a.type else None, type_b=b.type.value if b.type else None,
        voltage_a=a.voltage_kv, voltage_b=b.voltage_kv, radius=radius,
    )
    shared = t.shared if t else None
    band = distance_band(row.miles)
    pair_tier = tier(band)
    shared_km = None if row.shared_km is None else round(row.shared_km, 2)
    return CoordinationPairDTO(
        id=pair_id(a.id, b.id), project_a=a, project_b=b, miles=round(row.miles, 3),
        band=band, tier=pair_tier,
        overlap_days=t.overlap_days if t else 0,
        overlap_ratio=round(t.ratio, 4) if t else None,
        time_gap_days=t.in_service_gap_days if t else None,
        window_start=shared.start if shared else None,
        window_end=shared.end if shared else None,
        build_a=(wa.start, wa.end) if wa else None,
        build_b=(wb.start, wb.end) if wb else None,
        shared_km=shared_km, link=row.link, scores=scores,
        impact=estimate(tier=pair_tier, a=a, b=b, shared_km=shared_km,
                        windows_overlap=shared is not None),
    )


def parse_utilities(raw: list[str] | None) -> list[str] | None:
    """Repeated `utility` params -> the utilities to keep, or None (no filter) when absent
    or all blank."""
    names = [u.strip() for u in raw or [] if u.strip()]
    return names or None


async def overlaps(
    conn: asyncpg.Connection, radius: float, *, bands: set[str] | None = None,
    utilities: list[str] | None = None, rules: Rules | None = None,
) -> list[CoordinationPairDTO]:
    """Every match, ranked: within `radius` and close in time (`qualifies`). `utilities`
    keeps only pairs between those utilities, filtered in SQL so a two-utility view doesn't
    build thousands of pairs it would drop."""
    rules = rules or Rules.current()
    rows = await repo.candidate_pairs(conn, radius, utilities=utilities)
    if bands is not None:
        rows = [r for r in rows if distance_band(r.miles) in bands]
    projects = await repo.get_projects(conn, sorted({i for r in rows for i in (r.a_id, r.b_id)}))
    rows = _current(_cross_entity(rows, projects), projects, rules)
    pairs = [p for p in (_build_pair(r, projects, radius) for r in rows) if qualifies(p, rules)]
    briefs = await repo.briefs_for_pairs(conn, [p.id for p in pairs])
    for p in pairs:
        if p.id in briefs:
            p.brief = briefs[p.id].to_dto()
    pairs.sort(key=rank_key)
    return pairs


async def find_pair(
    conn: asyncpg.Connection, a_id: int, b_id: int, radius: float
) -> CoordinationPairDTO | None:
    rows = await repo.candidate_pairs(conn, radius, pair=(a_id, b_id))
    if not rows:
        return None
    projects = await repo.get_projects(conn, [a_id, b_id])
    if not _cross_entity(rows, projects):
        return None
    pair = _build_pair(rows[0], projects, radius)
    return pair if qualifies(pair, Rules.current()) else None


@dataclass
class RematchResult:
    pairs: list[CoordinationPairDTO]
    invalidated: list[str]
    updated: list[str]


async def rematch_project(conn: asyncpg.Connection, project_id: int) -> RematchResult:
    """Re-run matching for one edited project and fix up its stored pairs (Req 13.4).

    Pairs that carry a stored brief are re-checked under the radius they were flagged
    with and the current timing rules: no longer qualifying -> invalidated (removed); still
    qualifying -> facts refreshed, and the brief marked stale if the facts changed.
    """
    radius = get_settings().default_radius_miles
    rules = Rules.current()
    rows = await repo.candidate_pairs(conn, radius, project_id=project_id)
    briefs = await repo.briefs_for_project(conn, project_id)
    # Re-check every briefed pair in one query instead of a match query per brief.
    qualifying = await repo.qualifying_brief_pairs(conn, project_id) if briefs else {}
    ids = {i for r in [*rows, *qualifying.values()] for i in (r.a_id, r.b_id)}
    projects = await repo.get_projects(conn, sorted(ids))
    rows = _cross_entity(rows, projects)
    qualifying = {k: r for k, r in qualifying.items() if _cross_entity([r], projects)}
    pairs = [p for p in (_build_pair(r, projects, radius) for r in rows) if qualifies(p, rules)]

    invalidated: list[str] = []
    updated: list[str] = []
    for brief in briefs:
        row = qualifying.get(brief.pair_id)
        still = _build_pair(row, projects, brief.radius) if row else None
        if still is None or not qualifies(still, rules):
            await repo.delete_brief(conn, brief.pair_id)
            invalidated.append(brief.pair_id)
            continue
        if abs(still.miles - brief.miles) > 1e-3 or still.overlap_days != brief.overlap_days:
            await repo.refresh_brief_facts(conn, brief.pair_id, still.miles, still.overlap_days)
            updated.append(brief.pair_id)
    return RematchResult(pairs=pairs, invalidated=invalidated, updated=updated)
