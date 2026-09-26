"""Background worker: extraction -> geocoding -> persistence for one accepted plan."""

from __future__ import annotations

import asyncio
import logging

import asyncpg

from app.core.errors import ExtractionFailedError
from app.db import repository as repo
from app.models.enums import PlanStatus
from app.services.extraction import ExtractedProject, ExtractionService
from app.services.geocoding import GeocodingService
from app.services.parsing import ParsedDocument

log = logging.getLogger(__name__)
GEOCODE_CONCURRENCY = 4


async def to_new_project(
    p: ExtractedProject, geocoding: GeocodingService, *, plan_id: str, source_url: str
) -> repo.NewProject:
    outcome = await geocoding.geocode(p.location_ref, kind=p.location_kind, state=p.state or None)
    start = p.start_date.materialize()[0] if p.start_date else None
    end = p.end_date.materialize()[1] if p.end_date else None
    return repo.NewProject(
        plan_id=plan_id,
        utility=p.utility,
        state=p.state or None,
        name=p.name or None,
        type=p.type,
        voltage_kv=p.voltage_kv,
        location_ref=p.location_ref or None,
        lat=outcome.lat,
        lng=outcome.lng,
        approximate=outcome.approximate,
        requires_review=outcome.requires_review,
        start_date=start,
        end_date=end,
        start_precision=p.start_date.precision if p.start_date else None,
        end_precision=p.end_date.precision if p.end_date else None,
        confidence=p.confidence,
        source_url=source_url,
        source_page=p.source_page,
        length_mi=p.length_mi,
        capacity_mw=p.capacity_mw,
        stated_cost_musd=p.stated_cost_musd,
        cost_year=p.cost_year,
        raw_excerpt=p.raw_excerpt or None,
        reviewed=False,  # Req 3.2
    )


async def process_plan(
    pool: asyncpg.Pool,
    plan_id: str,
    document: ParsedDocument,
    *,
    utility: str,
    source_url: str,
    extraction: ExtractionService,
    geocoding: GeocodingService,
) -> None:
    try:
        extracted = await extraction.extract(document, utility=utility)
    except ExtractionFailedError as exc:
        # Req 2.9: no Project records; failure surfaced via the plan status.
        log.warning("extraction failed for plan %s: %s", plan_id, exc.message)
        async with pool.acquire() as conn:
            await repo.set_plan_status(conn, plan_id, PlanStatus.FAILED, error=exc.message)
        return

    try:
        sem = asyncio.Semaphore(GEOCODE_CONCURRENCY)

        async def convert(p: ExtractedProject) -> repo.NewProject:
            async with sem:
                return await to_new_project(p, geocoding, plan_id=plan_id, source_url=source_url)

        new_projects = await asyncio.gather(*(convert(p) for p in extracted))
        async with pool.acquire() as conn, conn.transaction():
            await repo.insert_projects(conn, list(new_projects))
            await repo.set_plan_status(
                conn, plan_id, PlanStatus.COMPLETE, project_count=len(new_projects)
            )
    except Exception as exc:
        log.exception("processing failed for plan %s", plan_id)
        async with pool.acquire() as conn:
            await repo.set_plan_status(conn, plan_id, PlanStatus.FAILED, error=str(exc))
