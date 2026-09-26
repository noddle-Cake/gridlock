from __future__ import annotations

from typing import Any

from fastapi import APIRouter, BackgroundTasks, File, Form, Query, Request, Response, UploadFile
from pydantic import ValidationError

from app.core.config import get_settings
from app.core.errors import (
    InvalidFieldError,
    InvalidParameterError,
    PairNotFoundError,
    PlanNotFoundError,
    ProjectNotFoundError,
    TooManyUtilitiesError,
)
from app.db import repository as repo
from app.models.dto import (
    CoordinationBriefDTO,
    IngestResult,
    OverlapsResponse,
    PlanDTO,
    ProjectDTO,
    ProjectPatch,
)
from app.services import export as export_service
from app.services import matching
from app.services.ingestion import validate_upload
from app.services.pipeline import process_plan

router = APIRouter()


def _state(request: Request) -> Any:
    return request.app.state


@router.get("/health")
async def health() -> dict:
    return {"status": "ok"}


# ---------------------------------------------------------------- ingestion (Req 1)


@router.post("/ingest", status_code=202, response_model=IngestResult)
async def ingest(
    request: Request,
    background: BackgroundTasks,
    file: UploadFile | None = File(default=None),
    utility: str | None = Form(default=None),
    source_url: str | None = Form(default=None),
) -> IngestResult:
    state = _state(request)
    upload = await validate_upload(file, utility, source_url)  # raises; persists nothing

    async with state.pool.acquire() as conn:
        existing = await repo.distinct_utilities(conn)
        limit = get_settings().max_utilities
        if upload.utility.lower() not in existing and len(existing) >= limit:
            raise TooManyUtilitiesError(
                f"A dataset supports at most {limit} distinct utilities.", field="utility"
            )
        plan = await repo.insert_plan(
            conn, utility=upload.utility, source_url=upload.source_url,
            filename=upload.filename, detected_format=upload.format,
        )

    background.add_task(
        process_plan, state.pool, plan.plan_id, upload.document,
        utility=upload.utility, source_url=upload.source_url,
        extraction=state.extraction, geocoding=state.geocoding,
    )
    return IngestResult(plan_id=plan.plan_id, utility=plan.utility, source_url=plan.source_url)


@router.get("/plans", response_model=list[PlanDTO])
async def list_plans(request: Request) -> list[PlanDTO]:
    async with _state(request).pool.acquire() as conn:
        return await repo.list_plans(conn)


@router.get("/plans/{plan_id}", response_model=PlanDTO)
async def get_plan(plan_id: str, request: Request) -> PlanDTO:
    async with _state(request).pool.acquire() as conn:
        plan = await repo.get_plan(conn, plan_id)
    if plan is None:
        raise PlanNotFoundError(f"Plan {plan_id} was not found.")
    return plan


# ---------------------------------------------------------------- projects (Req 5, 13)


@router.get("/projects", response_model=list[ProjectDTO])
async def list_projects(request: Request) -> list[ProjectDTO]:
    async with _state(request).pool.acquire() as conn:
        return await repo.list_projects(conn)


def _validate_patch(body: Any) -> dict[str, Any]:
    if not isinstance(body, dict):
        raise InvalidFieldError("The request body must be a JSON object.", fields=["body"])
    body = {k: (None if v == "" and k != "utility" else v) for k, v in body.items()}
    try:
        patch = ProjectPatch.model_validate(body)
    except ValidationError as exc:
        fields: list[str] = []
        messages: list[str] = []
        for err in exc.errors():
            loc = [str(x) for x in err["loc"]]
            if loc:
                names = [loc[0]]
            else:  # model-level check: name the fields its message is about
                names = [f for f in ("lat", "lng", "utility", "reviewed") if f in err["msg"]]
            for name in names or ["body"]:
                if name not in fields:
                    fields.append(name)
            messages.append(f"{', '.join(names or ['body'])}: {err['msg']}")
        raise InvalidFieldError(
            "Invalid field values: " + "; ".join(messages), field=fields[0], fields=fields
        ) from exc
    return patch.model_dump(include=patch.model_fields_set)


@router.patch("/projects/{project_id}", response_model=ProjectDTO)
async def patch_project(project_id: str, request: Request) -> ProjectDTO:
    try:
        body = await request.json()
    except ValueError as exc:
        raise InvalidFieldError("The request body is not valid JSON.", fields=["body"]) from exc
    changes = _validate_patch(body)

    pid = int(project_id) if project_id.isdigit() else None
    async with _state(request).pool.acquire() as conn, conn.transaction():
        current = await repo.get_project(conn, pid) if pid is not None else None
        if current is None:
            raise ProjectNotFoundError(f"Project {project_id} was not found.", field="id")

        start = changes.get("start_date", current.start_date)
        end = changes.get("end_date", current.end_date)
        if start and end and start > end:
            bad = [f for f in ("start_date", "end_date") if f in changes]
            raise InvalidFieldError(
                "Invalid field values: start_date must not be after end_date.",
                field=bad[0], fields=bad,
            )
        if "lat" in changes and changes["lat"] is not None and "approximate" not in changes:
            changes["approximate"] = False  # a planner-placed pin is exact

        updated = await repo.update_project(conn, pid, changes)
        if updated is None:
            raise ProjectNotFoundError(f"Project {project_id} was not found.", field="id")

        # Req 13.4: geom/date edits immediately re-run matching for this project.
        if {"lat", "lng", "start_date", "end_date"} & changes.keys():
            await matching.rematch_project(conn, pid)
    return updated


# ---------------------------------------------------------------- matching (Req 6, 7, 10)


@router.get("/overlaps", response_model=OverlapsResponse)
async def get_overlaps(
    request: Request,
    radius: str | None = Query(default=None),
    pad: str | None = Query(default=None),
) -> OverlapsResponse:
    radius_v, pad_v = matching.parse_thresholds(radius, pad)
    async with _state(request).pool.acquire() as conn:
        pairs = await matching.overlaps(conn, radius_v, pad_v)
    return OverlapsResponse(
        radius=radius_v, pad=pad_v, max_overlap_days=get_settings().max_overlap_days,
        pairs=pairs,
    )


@router.post("/overlaps/{pair_id}/brief", response_model=CoordinationBriefDTO)
async def create_brief(
    pair_id: str,
    request: Request,
    radius: str | None = Query(default=None),
    pad: str | None = Query(default=None),
) -> CoordinationBriefDTO:
    radius_v, pad_v = matching.parse_thresholds(radius, pad)
    ids = matching.parse_pair_id(pair_id)
    state = _state(request)
    async with state.pool.acquire() as conn:
        pair = await matching.find_pair(conn, *ids, radius_v, pad_v) if ids else None
    if pair is None:
        raise PairNotFoundError(f"Coordination pair {pair_id} was not found.")

    text = await state.brief_generator.generate(pair)  # raises 504 / 502; pair untouched

    async with state.pool.acquire() as conn:
        stored = await repo.upsert_brief(
            conn, pair_id=pair.id, a_id=pair.project_a.id, b_id=pair.project_b.id, text=text,
            miles=pair.miles, overlap_days=pair.overlap_days, radius=radius_v, pad=pad_v,
        )
    return stored.to_dto()


# ---------------------------------------------------------------- export (Req 14, Stretch)


@router.get("/export")
async def export(
    request: Request,
    format: str = Query(default="csv"),
    radius: str | None = Query(default=None),
    pad: str | None = Query(default=None),
) -> Response:
    fmt = format.lower()
    if fmt not in ("csv", "pdf"):
        raise InvalidParameterError("format must be 'csv' or 'pdf'.", field="format",
                                    fields=["format"])
    radius_v, pad_v = matching.parse_thresholds(radius, pad)
    async with _state(request).pool.acquire() as conn:
        pairs = await matching.overlaps(conn, radius_v, pad_v)
    records = export_service.to_records(pairs)
    if fmt == "csv":
        return Response(
            export_service.render_csv(records), media_type="text/csv",
            headers={"Content-Disposition": 'attachment; filename="gridlock-briefs.csv"'},
        )
    return Response(
        export_service.render_pdf(records), media_type="application/pdf",
        headers={"Content-Disposition": 'attachment; filename="gridlock-briefs.pdf"'},
    )
