"""Parameterized data access for plans, projects, and briefs (Req 5, 13)."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any

import asyncpg

from app.models.dto import CoordinationBriefDTO, PlanDTO, ProjectDTO
from app.models.enums import DatePrecision, PlanStatus, ProjectType

METERS_PER_MILE = 1609.344

_PROJECT_COLUMNS = """
    id, plan_id::text AS plan_id, utility, state, name, type, voltage_kv, location_ref,
    ST_Y(geom::geometry) AS lat, ST_X(geom::geometry) AS lng,
    start_date, end_date, start_precision, end_precision, confidence, source_url,
    source_page, raw_excerpt, reviewed, approximate, requires_review
"""

# Columns a PATCH may write directly (lat/lng are handled via geom).
EDITABLE_COLUMNS = {
    "utility", "state", "name", "type", "voltage_kv", "location_ref", "start_date",
    "end_date", "confidence", "source_url", "source_page", "raw_excerpt", "reviewed",
    "approximate",
}


@dataclass
class NewProject:
    utility: str
    confidence: float
    state: str | None = None
    name: str | None = None
    type: ProjectType | None = None
    voltage_kv: float | None = None
    location_ref: str | None = None
    lat: float | None = None
    lng: float | None = None
    start_date: date | None = None
    end_date: date | None = None
    start_precision: DatePrecision | None = None
    end_precision: DatePrecision | None = None
    source_url: str | None = None
    source_page: int | None = None
    raw_excerpt: str | None = None
    reviewed: bool = False
    approximate: bool = False
    requires_review: bool = False
    plan_id: str | None = None


@dataclass
class CandidateRow:
    a_id: int
    b_id: int
    miles: float
    overlap_days: int
    window_start: date
    window_end: date


@dataclass
class StoredBrief:
    pair_id: str
    a_id: int
    b_id: int
    text: str
    miles: float
    overlap_days: int
    radius: float
    pad: int
    stale: bool
    generated_at: datetime
    extra: dict[str, Any] = field(default_factory=dict)

    def to_dto(self) -> CoordinationBriefDTO:
        return CoordinationBriefDTO(
            pair_id=self.pair_id, text=self.text, generated_at=self.generated_at,
            stale=self.stale,
        )


def clean(value: Any) -> Any:
    """Postgres text cannot hold NUL; PDF/LLM text occasionally contains it."""
    return value.replace("\x00", "") if isinstance(value, str) else value


def round_voltage(v: float | None) -> int | None:
    """voltage_kv is stored as int; round to the nearest kV but never below 1."""
    if v is None:
        return None
    return max(1, int(round(v)))


def _project_from_record(r: asyncpg.Record) -> ProjectDTO:
    return ProjectDTO(**dict(r))


# ---------------------------------------------------------------- plans


async def insert_plan(
    conn: asyncpg.Connection, *, utility: str, source_url: str, filename: str | None,
    detected_format: str, page_range: str | None = None,
) -> PlanDTO:
    r = await conn.fetchrow(
        """INSERT INTO plans (id, utility, source_url, filename, detected_format, page_range)
           VALUES ($1, $2, $3, $4, $5, $6)
           RETURNING id::text AS plan_id, utility, source_url, filename, detected_format,
                     status, error, project_count, created_at, page_range""",
        uuid.uuid4(), clean(utility), clean(source_url), clean(filename), detected_format,
        page_range,
    )
    return PlanDTO(**dict(r))


async def set_plan_status(
    conn: asyncpg.Connection, plan_id: str, status: PlanStatus, *, error: str | None = None,
    project_count: int = 0,
) -> None:
    await conn.execute(
        "UPDATE plans SET status = $2, error = $3, project_count = $4 WHERE id = $1::uuid",
        plan_id, status.value, error, project_count,
    )


async def get_plan(conn: asyncpg.Connection, plan_id: str) -> PlanDTO | None:
    try:
        uuid.UUID(plan_id)
    except ValueError:
        return None
    r = await conn.fetchrow(
        """SELECT id::text AS plan_id, utility, source_url, filename, detected_format, status,
                  error, project_count, created_at, page_range FROM plans WHERE id = $1::uuid""",
        plan_id,
    )
    return PlanDTO(**dict(r)) if r else None


async def list_plans(conn: asyncpg.Connection) -> list[PlanDTO]:
    rows = await conn.fetch(
        """SELECT id::text AS plan_id, utility, source_url, filename, detected_format, status,
                  error, project_count, created_at, page_range
           FROM plans ORDER BY created_at DESC"""
    )
    return [PlanDTO(**dict(r)) for r in rows]


async def distinct_utilities(conn: asyncpg.Connection) -> set[str]:
    rows = await conn.fetch(
        "SELECT DISTINCT lower(trim(utility)) AS u FROM plans WHERE status <> 'failed'"
    )
    return {r["u"] for r in rows}


# ---------------------------------------------------------------- projects


async def insert_projects(conn: asyncpg.Connection, projects: list[NewProject]) -> list[int]:
    ids: list[int] = []
    for p in projects:
        pid = await conn.fetchval(
            """INSERT INTO projects (
                 plan_id, utility, state, name, type, voltage_kv, location_ref, geom,
                 start_date, end_date, start_precision, end_precision, confidence,
                 source_url, source_page, raw_excerpt, reviewed, approximate, requires_review)
               VALUES ($1::uuid, $2, $3, $4, $5, $6, $7,
                 CASE WHEN $8::float8 IS NULL OR $9::float8 IS NULL THEN NULL
                      ELSE ST_SetSRID(ST_MakePoint($9, $8), 4326)::geography END,
                 $10, $11, $12, $13, $14, $15, $16, $17, $18, $19, $20)
               RETURNING id""",
            p.plan_id, clean(p.utility).strip(), clean(p.state), clean(p.name),
            p.type.value if p.type else None, round_voltage(p.voltage_kv), clean(p.location_ref),
            p.lat, p.lng, p.start_date, p.end_date,
            p.start_precision.value if p.start_precision else None,
            p.end_precision.value if p.end_precision else None,
            p.confidence, clean(p.source_url), p.source_page, clean(p.raw_excerpt), p.reviewed,
            p.approximate, p.requires_review,
        )
        ids.append(pid)
    return ids


async def get_project(conn: asyncpg.Connection, project_id: int) -> ProjectDTO | None:
    r = await conn.fetchrow(f"SELECT {_PROJECT_COLUMNS} FROM projects WHERE id = $1", project_id)
    return _project_from_record(r) if r else None


async def get_projects(conn: asyncpg.Connection, ids: list[int]) -> dict[int, ProjectDTO]:
    if not ids:
        return {}
    rows = await conn.fetch(
        f"SELECT {_PROJECT_COLUMNS} FROM projects WHERE id = ANY($1::int[])", ids
    )
    return {r["id"]: _project_from_record(r) for r in rows}


async def list_projects(conn: asyncpg.Connection) -> list[ProjectDTO]:
    rows = await conn.fetch(f"SELECT {_PROJECT_COLUMNS} FROM projects ORDER BY utility, id")
    return [_project_from_record(r) for r in rows]


async def update_project(
    conn: asyncpg.Connection, project_id: int, changes: dict[str, Any]
) -> ProjectDTO | None:
    """Apply a pre-validated change set. `lat`/`lng` (together) rewrite geom."""
    sets: list[str] = []
    args: list[Any] = [project_id]

    def arg(value: Any) -> str:
        args.append(value)
        return f"${len(args)}"

    for col, value in changes.items():
        if col in ("lat", "lng"):
            continue
        if col not in EDITABLE_COLUMNS:
            raise ValueError(f"not an editable column: {col}")
        if col == "type" and value is not None:
            value = ProjectType(value).value
        if col == "voltage_kv":
            value = round_voltage(value)
        if col in ("start_date", "end_date"):
            prec_col = col.replace("date", "precision")
            sets.append(f"{prec_col} = {arg(None if value is None else DatePrecision.DAY.value)}")
        sets.append(f"{col} = {arg(clean(value))}")

    if "lat" in changes:
        lat, lng = changes["lat"], changes["lng"]
        if lat is None:
            sets.append("geom = NULL")
        else:
            sets.append(
                f"geom = ST_SetSRID(ST_MakePoint({arg(float(lng))}, {arg(float(lat))}), 4326)"
                "::geography"
            )
            sets.append("requires_review = false")

    if not sets:
        return await get_project(conn, project_id)
    r = await conn.fetchrow(
        f"UPDATE projects SET {', '.join(sets)} WHERE id = $1 RETURNING {_PROJECT_COLUMNS}",
        *args,
    )
    return _project_from_record(r) if r else None


# ---------------------------------------------------------------- matching

_CANDIDATE_SQL = """
WITH p AS (
  SELECT id, lower(trim(utility)) AS u, geom,
         COALESCE(start_date, end_date) AS s,
         COALESCE(end_date, start_date) AS e
  FROM projects
  WHERE geom IS NOT NULL                                   -- Req 6.8
    AND COALESCE(start_date, end_date) IS NOT NULL
)
SELECT a.id AS a_id, b.id AS b_id,
       ST_Distance(a.geom, b.geom) / {mpm} AS miles,
       GREATEST(a.s, b.s) - $2::int AS window_start,
       LEAST(a.e, b.e) + $2::int AS window_end
FROM p a
JOIN p b ON a.id < b.id AND a.u <> b.u                     -- Req 6.2: different utilities
WHERE ST_DWithin(a.geom, b.geom, $1)                       -- Req 6.3
  AND a.s - $2::int <= b.e + $2::int                       -- Req 6.4: padded ranges overlap
  AND b.s - $2::int <= a.e + $2::int
  {extra}
ORDER BY miles
""".replace("{mpm}", str(METERS_PER_MILE))


def _candidate_from_record(r: asyncpg.Record) -> CandidateRow:
    start, end = r["window_start"], r["window_end"]
    return CandidateRow(
        a_id=r["a_id"], b_id=r["b_id"], miles=float(r["miles"]),
        # Inclusive day count shared by the two padded ranges (Req 6.10).
        overlap_days=(end - start).days + 1,
        window_start=start, window_end=end,
    )


async def candidate_pairs(
    conn: asyncpg.Connection, radius_miles: float, pad_days: int,
    *, project_id: int | None = None, pair: tuple[int, int] | None = None,
) -> list[CandidateRow]:
    args: list[Any] = [radius_miles * METERS_PER_MILE, pad_days]
    extra = ""
    if project_id is not None:
        args.append(project_id)
        extra = "AND (a.id = $3 OR b.id = $3)"
    elif pair is not None:
        args.extend(sorted(pair))
        extra = "AND a.id = $3 AND b.id = $4"
    rows = await conn.fetch(_CANDIDATE_SQL.replace("{extra}", extra), *args)
    return [_candidate_from_record(r) for r in rows]


# ---------------------------------------------------------------- briefs


def _brief_from_record(r: asyncpg.Record) -> StoredBrief:
    return StoredBrief(**dict(r))


async def upsert_brief(
    conn: asyncpg.Connection, *, pair_id: str, a_id: int, b_id: int, text: str, miles: float,
    overlap_days: int, radius: float, pad: int,
) -> StoredBrief:
    r = await conn.fetchrow(
        """INSERT INTO briefs (pair_id, a_id, b_id, text, miles, overlap_days, radius, pad)
           VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
           ON CONFLICT (pair_id) DO UPDATE SET text = EXCLUDED.text, miles = EXCLUDED.miles,
             overlap_days = EXCLUDED.overlap_days, radius = EXCLUDED.radius,
             pad = EXCLUDED.pad, stale = false, generated_at = now()
           RETURNING *""",
        pair_id, a_id, b_id, clean(text), miles, overlap_days, radius, pad,
    )
    return _brief_from_record(r)


async def briefs_for_pairs(
    conn: asyncpg.Connection, pair_ids: list[str]
) -> dict[str, StoredBrief]:
    if not pair_ids:
        return {}
    rows = await conn.fetch("SELECT * FROM briefs WHERE pair_id = ANY($1::text[])", pair_ids)
    return {r["pair_id"]: _brief_from_record(r) for r in rows}


async def briefs_for_project(conn: asyncpg.Connection, project_id: int) -> list[StoredBrief]:
    rows = await conn.fetch("SELECT * FROM briefs WHERE a_id = $1 OR b_id = $1", project_id)
    return [_brief_from_record(r) for r in rows]


async def delete_brief(conn: asyncpg.Connection, pair_id: str) -> None:
    await conn.execute("DELETE FROM briefs WHERE pair_id = $1", pair_id)


async def refresh_brief_facts(
    conn: asyncpg.Connection, pair_id: str, miles: float, overlap_days: int
) -> None:
    """The pair still qualifies after an edit: update its facts and flag the text stale."""
    await conn.execute(
        "UPDATE briefs SET miles = $2, overlap_days = $3, stale = true WHERE pair_id = $1",
        pair_id, miles, overlap_days,
    )
