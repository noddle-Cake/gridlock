"""Matching_Engine: PostGIS candidate query + Python scoring (Req 6, 7, 13.4)."""

from __future__ import annotations

import math
from dataclasses import dataclass

import asyncpg

from app.core.config import get_settings
from app.core.errors import InvalidParameterError
from app.db import repository as repo
from app.models.dto import CoordinationPairDTO, ProjectDTO
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


def parse_thresholds(radius: str | None, pad: str | None) -> tuple[float, int]:
    """Validate query params; report every invalid one in a single error (Req 6.5-6.7)."""
    settings = get_settings()
    invalid: list[str] = []
    reasons: list[str] = []

    def number(name: str, raw: str | None, default: float) -> float:
        if raw is None or raw.strip() == "":
            return default
        try:
            value = float(raw)
        except ValueError:
            invalid.append(name)
            reasons.append(f"{name} must be numeric (got {raw!r})")
            return default
        if not math.isfinite(value):
            invalid.append(name)
            reasons.append(f"{name} must be a finite number (got {raw!r})")
            return default
        if value < 0:
            invalid.append(name)
            reasons.append(f"{name} must not be negative (got {raw!r})")
            return default
        return value

    radius_v = number("radius", radius, settings.default_radius_miles)
    pad_v = number("pad", pad, settings.default_pad_days)
    if invalid:
        raise InvalidParameterError("; ".join(reasons), fields=invalid, field=invalid[0])
    return radius_v, int(round(pad_v))


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


def _build_pair(
    row: repo.CandidateRow, projects: dict[int, ProjectDTO], radius: float, max_overlap: int
) -> CoordinationPairDTO:
    a, b = projects[row.a_id], projects[row.b_id]
    scores = score_pair(
        # Undated projects: timing is unknown (factor flagged indeterminate), not "no overlap".
        miles=row.miles, overlap_days=None if row.time_gap_days is None else row.overlap_days,
        type_a=a.type.value if a.type else None, type_b=b.type.value if b.type else None,
        voltage_a=a.voltage_kv, voltage_b=b.voltage_kv,
        radius=radius, max_overlap=max_overlap,
    )
    return CoordinationPairDTO(
        id=pair_id(a.id, b.id), project_a=a, project_b=b,
        miles=round(row.miles, 3), overlap_days=row.overlap_days,
        time_gap_days=row.time_gap_days, window_start=row.window_start,
        window_end=row.window_end, scores=scores,
    )


async def overlaps(
    conn: asyncpg.Connection, radius: float, pad: int, *, max_overlap: int | None = None,
    bands: set[str] | None = None,
) -> list[CoordinationPairDTO]:
    max_overlap = max_overlap or get_settings().max_overlap_days
    rows = await repo.candidate_pairs(conn, radius, pad)
    if bands is not None:
        rows = [r for r in rows if distance_band(r.miles) in bands]
    projects = await repo.get_projects(conn, sorted({i for r in rows for i in (r.a_id, r.b_id)}))
    pairs = [_build_pair(r, projects, radius, max_overlap) for r in rows]
    briefs = await repo.briefs_for_pairs(conn, [p.id for p in pairs])
    for p in pairs:
        if p.id in briefs:
            p.brief = briefs[p.id].to_dto()
    pairs.sort(key=lambda p: p.scores.composite, reverse=True)
    return pairs


async def find_pair(
    conn: asyncpg.Connection, a_id: int, b_id: int, radius: float, pad: int
) -> CoordinationPairDTO | None:
    rows = await repo.candidate_pairs(conn, radius, pad, pair=(a_id, b_id))
    if not rows:
        return None
    projects = await repo.get_projects(conn, [a_id, b_id])
    return _build_pair(rows[0], projects, radius, get_settings().max_overlap_days)


@dataclass
class RematchResult:
    pairs: list[CoordinationPairDTO]
    invalidated: list[str]
    updated: list[str]


async def rematch_project(conn: asyncpg.Connection, project_id: int) -> RematchResult:
    """Re-run matching for one edited project and fix up its stored pairs (Req 13.4).

    Pairs that carry a stored brief are re-checked under the thresholds they were
    flagged with: no longer qualifying -> invalidated (removed); still qualifying
    -> facts refreshed, and the brief marked stale if the facts changed.
    """
    settings = get_settings()
    rows = await repo.candidate_pairs(
        conn, settings.default_radius_miles, settings.default_pad_days, project_id=project_id
    )
    projects = await repo.get_projects(conn, sorted({i for r in rows for i in (r.a_id, r.b_id)}))
    pairs = [
        _build_pair(r, projects, settings.default_radius_miles, settings.max_overlap_days)
        for r in rows
    ]

    invalidated: list[str] = []
    updated: list[str] = []
    for brief in await repo.briefs_for_project(conn, project_id):
        still = await repo.candidate_pairs(
            conn, brief.radius, brief.pad, pair=(brief.a_id, brief.b_id)
        )
        if not still:
            await repo.delete_brief(conn, brief.pair_id)
            invalidated.append(brief.pair_id)
            continue
        row = still[0]
        if abs(row.miles - brief.miles) > 1e-6 or row.overlap_days != brief.overlap_days:
            await repo.refresh_brief_facts(conn, brief.pair_id, row.miles, row.overlap_days)
            updated.append(brief.pair_id)
    return RematchResult(pairs=pairs, invalidated=invalidated, updated=updated)
