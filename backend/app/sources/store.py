"""Idempotent persistence for loader output: one plan row per source file."""

from __future__ import annotations

import asyncpg

from app.db import repository as repo
from app.models.enums import PlanStatus

LOADER_SUFFIX = " [loader]"  # marks plans written by a loader, not by an upload


async def replace_source(
    conn: asyncpg.Connection, *, label: str, source_url: str, filename: str,
    detected_format: str, projects: list[repo.NewProject], page_range: str | None = None,
    snapshot_sha: str | None = None,
) -> str:
    """Delete this loader's previous run of `source_url` (projects and briefs cascade),
    then insert the plan and its projects in one transaction. Plans uploaded through
    /ingest for the same URL are left alone. `snapshot_sha` records which committed
    snapshot the rows match."""
    tagged = filename + LOADER_SUFFIX
    async with conn.transaction():
        await conn.execute(
            "DELETE FROM plans WHERE source_url = $1 AND filename = $2", source_url, tagged
        )
        plan = await repo.insert_plan(
            conn, utility=label, source_url=source_url, filename=tagged,
            detected_format=detected_format, page_range=page_range,
        )
        for p in projects:
            p.plan_id = plan.plan_id
        await repo.insert_projects(conn, projects)
        await repo.set_plan_status(
            conn, plan.plan_id, PlanStatus.COMPLETE, project_count=len(projects)
        )
        await conn.execute(
            "UPDATE plans SET snapshot_sha = $2 WHERE id = $1::uuid", plan.plan_id, snapshot_sha
        )
    return plan.plan_id
