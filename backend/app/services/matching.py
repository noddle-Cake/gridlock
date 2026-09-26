"""Matching_Engine: PostGIS candidate query + Python scoring (Req 6, 7, 13.4)."""

from __future__ import annotations

import math
from dataclasses import dataclass

import asyncpg

from app.core.config import get_settings
from app.core.errors import InvalidParameterError
from app.db import repository as repo
from app.models.dto import CoordinationPairDTO, ProjectDTO
from app.services import timing
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


def _window(p: ProjectDTO) -> timing.Window | None:
    return timing.build_window(p.start_date, p.end_date, p.start_precision, p.end_precision)


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
    return CoordinationPairDTO(
        id=pair_id(a.id, b.id), project_a=a, project_b=b, miles=round(row.miles, 3),
        overlap_days=t.overlap_days if t else 0,
        overlap_ratio=round(t.ratio, 4) if t else None,
        time_gap_days=t.in_service_gap_days if t else None,
        window_start=shared.start if shared else None,
        window_end=shared.end if shared else None,
        scores=scores,
    )


async def overlaps(
    conn: asyncpg.Connection, radius: float, *, bands: set[str] | None = None,
) -> list[CoordinationPairDTO]:
    rows = await repo.candidate_pairs(conn, radius)
    if bands is not None:
        rows = [r for r in rows if distance_band(r.miles) in bands]
    projects = await repo.get_projects(conn, sorted({i for r in rows for i in (r.a_id, r.b_id)}))
    pairs = [_build_pair(r, projects, radius) for r in rows]
    briefs = await repo.briefs_for_pairs(conn, [p.id for p in pairs])
    for p in pairs:
        if p.id in briefs:
            p.brief = briefs[p.id].to_dto()
    pairs.sort(key=lambda p: p.scores.composite, reverse=True)
    return pairs


async def find_pair(
    conn: asyncpg.Connection, a_id: int, b_id: int, radius: float
) -> CoordinationPairDTO | None:
    rows = await repo.candidate_pairs(conn, radius, pair=(a_id, b_id))
    if not rows:
        return None
    projects = await repo.get_projects(conn, [a_id, b_id])
    return _build_pair(rows[0], projects, radius)


async def pairs_for_project(
    conn: asyncpg.Connection, project_id: int, radius: float
) -> list[CoordinationPairDTO]:
    """Every pair one project belongs to, best score first."""
    rows = await repo.candidate_pairs(conn, radius, project_id=project_id)
    projects = await repo.get_projects(conn, sorted({i for r in rows for i in (r.a_id, r.b_id)}))
    pairs = [_build_pair(r, projects, radius) for r in rows]
    return sorted(pairs, key=lambda p: p.scores.composite, reverse=True)


@dataclass
class RematchResult:
    pairs: list[CoordinationPairDTO]
    invalidated: list[str]
    updated: list[str]


async def rematch_project(conn: asyncpg.Connection, project_id: int) -> RematchResult:
    """Re-run matching for one edited project and fix up its stored pairs (Req 13.4).

    Pairs that carry a stored brief are re-checked under the radius they were flagged
    with: no longer qualifying -> invalidated (removed); still qualifying -> facts
    refreshed, and the brief marked stale if the facts changed.
    """
    radius = get_settings().default_radius_miles
    rows = await repo.candidate_pairs(conn, radius, project_id=project_id)
    briefs = await repo.briefs_for_project(conn, project_id)
    # Re-check every briefed pair in one query instead of a match query per brief.
    qualifying = await repo.qualifying_brief_pairs(conn, project_id) if briefs else {}
    ids = {i for r in [*rows, *qualifying.values()] for i in (r.a_id, r.b_id)}
    projects = await repo.get_projects(conn, sorted(ids))
    pairs = [_build_pair(r, projects, radius) for r in rows]

    invalidated: list[str] = []
    updated: list[str] = []
    for brief in briefs:
        row = qualifying.get(brief.pair_id)
        still = _build_pair(row, projects, brief.radius) if row else None
        if still is None:
            await repo.delete_brief(conn, brief.pair_id)
            invalidated.append(brief.pair_id)
            continue
        if abs(still.miles - brief.miles) > 1e-3 or still.overlap_days != brief.overlap_days:
            await repo.refresh_brief_facts(conn, brief.pair_id, still.miles, still.overlap_days)
            updated.append(brief.pair_id)
    return RematchResult(pairs=pairs, invalidated=invalidated, updated=updated)
