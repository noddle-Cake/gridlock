"""Ask GridMerge: a small Gemini agent that answers questions from GridMerge's own data.

Gemini only decides which tool to call and with what arguments; the tools run here,
against Postgres, through the same filters as the search bar (services/search.py). The
model is told to answer from tool results alone and to cite projects as [#id], and the
cited projects go back to the client so the answer links into the map.

    question -> Gemini -> search_gridmerge({"state": "GA", "type": "transmission line"})
             -> Postgres -> results -> Gemini -> answer
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from datetime import date
from typing import Any

import asyncpg

from app.core.config import get_settings
from app.core.errors import AskFailedError, AskTimeoutError, AskUnavailableError, GridMergeError
from app.db import repository as repo
from app.models.dto import AskResponse, AskToolCallDTO, CoordinationPairDTO, ProjectDTO
from app.models.enums import ProjectType
from app.services import matching, search
from app.services.llm import (
    DailyQuotaExhaustedError,
    LLMClient,
    LLMUnavailableError,
    ToolCall,
    ToolResult,
)

log = logging.getLogger(__name__)

TIMEOUT_S = 90.0  # the free tier paces requests ~12 s apart; a question takes 2-3
MAX_TOOL_ROUNDS = 4
MAX_SHOWN_PROJECTS = 8  # projects returned when the answer cites none

SYSTEM_INSTRUCTION = """You are the GridMerge research assistant. GridMerge tracks planned \
utility capital projects (generation, substations, transmission lines) taken from utility \
capital plans, EIA-860M, and SERTP, and flags "coordination pairs": projects of different \
utilities that are close together and built at overlapping times.

Rules:
- Answer only from what your tools return. Never invent utilities, projects, dates, \
costs, or counts. Call a tool before answering any question about the data.
- search_gridmerge reports exact totals and breakdowns by utility, state, and type over \
ALL matches; use those for "how many" and "which utilities" questions instead of \
counting the sample rows.
- A utility may be stored under its parent (Georgia Power projects can appear as Southern \
Company). If a company search finds nothing, retry with the name as `query` text.
- GridMerge does not track project costs or budgets; say so if asked.
- Cite specific projects by id in square brackets, like [#123].
- Say when the data looks incomplete for the question.
- Be brief: one direct sentence, then at most 8 short "- " bullets. The only formatting \
allowed is **bold** and "- " bullets.

Today's date is {today}."""

_TYPE_ENUM = [t.value for t in ProjectType]

TOOLS: list[dict[str, Any]] = [
    {
        "type": "function",
        "name": "search_gridmerge",
        "description": (
            "Search GridMerge's planned utility projects. Filters combine (AND). Returns "
            "the total match count, breakdowns by utility/state/type over all matches, "
            "the build-date span, and up to `limit` example projects."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "company": {"type": "string",
                            "description": "Utility/company name or acronym, e.g. FPL"},
                "state": {"type": "string",
                          "description": "US state name or two-letter abbreviation"},
                "zip": {"type": "string",
                        "description": "Five-digit ZIP code; matches projects near it"},
                "type": {"type": "string", "enum": _TYPE_ENUM},
                "query": {"type": "string",
                          "description": "Other words to match in project names/locations"},
                "limit": {"type": "integer", "description": "Example projects, 1-25"},
            },
        },
    },
    {
        "type": "function",
        "name": "get_project_details",
        "description": (
            "Full record for one project (source document, excerpt, location, dates) and "
            "the coordination pairs it belongs to, best score first."
        ),
        "parameters": {
            "type": "object",
            "properties": {"project_id": {"type": "integer"}},
            "required": ["project_id"],
        },
    },
    {
        "type": "function",
        "name": "find_coordination_overlaps",
        "description": (
            "Coordination pairs: two projects of different utilities within `max_miles` "
            "of each other, ranked by distance tier (0 = touching ... 3 = within 40 km), "
            "then by a score of distance, timing, type, and voltage. "
            "Optionally only pairs involving a company and/or a state."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "company": {"type": "string"},
                "state": {"type": "string"},
                "max_miles": {"type": "number", "description": "Pair radius, 1-50 miles"},
                "limit": {"type": "integer", "description": "Pairs to return, 1-20"},
            },
        },
    },
]


def _clamp(value: Any, lo: float, hi: float, default: float) -> float:
    try:
        v = float(value)
    except (TypeError, ValueError):
        return default
    return min(hi, max(lo, v))


def _iso(d: date | None) -> str | None:
    return d.isoformat() if d else None


def compact(p: ProjectDTO, miles: float | None = None) -> dict[str, Any]:
    """A project as the model sees it: the fields that answer questions, nothing null."""
    d = {
        "id": p.id, "utility": p.utility, "name": p.name,
        "type": p.type.value if p.type else None, "voltage_kv": p.voltage_kv,
        "state": p.state, "location": p.location_ref,
        "start": _iso(p.start_date), "end": _iso(p.end_date),
        "miles_from_zip": round(miles, 1) if miles is not None else None,
    }
    return {k: v for k, v in d.items() if v is not None}


def _in_state(p: ProjectDTO, code: str) -> bool:
    if p.state:
        return p.state.upper() == code
    return bool(re.search(repo.state_ref_pattern([code]), p.location_ref or ""))


def _pair(pair: CoordinationPairDTO, *, other_of: int | None = None) -> dict[str, Any]:
    d: dict[str, Any] = {
        "pair_id": pair.id, "score": round(pair.scores.composite, 2),
        "miles": round(pair.miles, 1), "overlap_days": pair.overlap_days,
    }
    if pair.tier is not None:
        d["tier"] = pair.tier  # 0 = touching ... 3 = within 40 km: can share crews
    if pair.window_start:
        d["shared_window"] = [_iso(pair.window_start), _iso(pair.window_end)]
    if other_of is None:
        d["project_a"], d["project_b"] = compact(pair.project_a), compact(pair.project_b)
    else:
        other = pair.project_b if pair.project_a.id == other_of else pair.project_a
        d["other_project"] = compact(other)
    return d


class ToolRun:
    """The outcome of one tool call: JSON for the model, projects and a label for the UI."""

    def __init__(self, payload: dict[str, Any], projects: list[ProjectDTO], summary: str):
        self.payload = payload
        self.projects = projects
        self.summary = summary


class AskService:
    def __init__(self, llm: LLMClient, *, timeout: float = TIMEOUT_S) -> None:
        self._llm = llm
        self._timeout = timeout

    async def ask(self, pool: asyncpg.Pool, question: str) -> AskResponse:
        """Never returns a partial answer: no key -> 503, timeout -> 504, else 502."""
        try:
            return await asyncio.wait_for(self._run(pool, question), timeout=self._timeout)
        except TimeoutError as exc:
            raise AskTimeoutError(
                f"Ask GridMerge timed out after {int(self._timeout)} seconds."
            ) from exc
        except GridMergeError:
            raise
        except DailyQuotaExhaustedError as exc:
            raise AskFailedError(str(exc)) from exc
        except LLMUnavailableError as exc:
            if "not configured" in str(exc):
                raise AskUnavailableError(
                    "AI answers are off: GEMINI_API_KEY is not configured on the server."
                ) from exc
            raise AskFailedError(f"Ask GridMerge failed: {exc}") from exc
        except Exception as exc:
            log.exception("ask failed")
            raise AskFailedError(f"Ask GridMerge failed: {exc}") from exc

    async def _run(self, pool: asyncpg.Pool, question: str) -> AskResponse:
        system = SYSTEM_INSTRUCTION.format(today=date.today().isoformat())
        turn = await self._llm.converse(system=system, tools=TOOLS, message=question)
        handled: set[str] = set()
        seen: dict[int, ProjectDTO] = {}
        log_: list[AskToolCallDTO] = []

        for round_ in range(MAX_TOOL_ROUNDS + 1):
            calls = [c for c in turn.calls if c.id not in handled]
            if not calls:
                break
            results: list[ToolResult] = []
            for call in calls:
                handled.add(call.id)
                if round_ == MAX_TOOL_ROUNDS:
                    # Out of budget: make the model answer with what it already has.
                    results.append(ToolResult(
                        call.id, call.name, json.dumps({"error": "Tool budget used up; "
                                                        "answer now from the results so far."}),
                        is_error=True,
                    ))
                    continue
                results.append(await self._execute(pool, call, seen, log_))
            turn = await self._llm.converse(
                system=system, tools=TOOLS, results=results, previous=turn.handle
            )

        answer = turn.text.strip()
        if not answer:
            raise AskFailedError("Gemini returned no answer.")
        return AskResponse(
            question=question, answer=answer,
            projects=await self._cited(pool, answer, seen), tool_calls=log_,
        )

    async def _execute(
        self, pool: asyncpg.Pool, call: ToolCall, seen: dict[int, ProjectDTO],
        log_: list[AskToolCallDTO],
    ) -> ToolResult:
        handlers = {
            "search_gridmerge": self._search,
            "get_project_details": self._details,
            "find_coordination_overlaps": self._overlaps,
        }
        handler = handlers.get(call.name)
        if handler is None:
            return ToolResult(call.id, call.name, json.dumps({"error": "unknown tool"}), True)
        try:
            async with pool.acquire() as conn:
                run = await handler(conn, call.arguments)
        except Exception as exc:  # a bad argument must not sink the whole answer
            log.warning("tool %s failed: %s", call.name, exc)
            log_.append(AskToolCallDTO(name=call.name, arguments=call.arguments,
                                       summary="failed"))
            return ToolResult(call.id, call.name, json.dumps({"error": str(exc)}), True)
        for p in run.projects:
            seen.setdefault(p.id, p)
        log_.append(AskToolCallDTO(name=call.name, arguments=call.arguments,
                                   summary=run.summary))
        return ToolResult(call.id, call.name, json.dumps(run.payload, default=str))

    # ------------------------------------------------------------ tools

    async def _search(self, conn: asyncpg.Connection, args: dict[str, Any]) -> ToolRun:
        companies = await search.load_companies(conn)
        parsed = search.parse_query(str(args.get("query") or ""), companies)
        if company := str(args.get("company") or "").strip():
            hits = companies.resolve(company)
            if hits:
                parsed.utilities = [*parsed.utilities, *(h for h in hits
                                                         if h not in parsed.utilities)]
            else:
                parsed.terms.append(company.lower())
        if state := str(args.get("state") or "").strip():
            code = search.state_code(state)
            if not code:
                raise ValueError(f"unknown US state {state!r}")
            parsed.states = [code]
        if zip_code := str(args.get("zip") or "").strip():
            parsed.zip = zip_code[:5]
        if kind := args.get("type"):
            t = ProjectType.coerce(kind)
            if t:
                parsed.types = [t]
        f, point = search.to_filter(parsed)
        if f.empty:
            raise ValueError("give at least one of company, state, zip, type, or query")
        limit = int(_clamp(args.get("limit"), 1, 25, 15))
        result, fuzzy = await search.search_with_fallback(conn, f, limit=limit)

        filters: dict[str, Any] = {
            "utilities": f.utilities, "states": f.states, "types": f.types,
            "terms": f.terms, "fuzzy_name_match": fuzzy,
        }
        if parsed.zip:
            filters["zip"] = parsed.zip
            filters["zip_found"] = point is not None
            if point:
                filters["radius_miles"] = f.radius_miles
        payload: dict[str, Any] = {
            "total_matches": result.total,
            "filters": {k: v for k, v in filters.items() if v not in ([], None)},
            "by_utility": [{"utility": u, "projects": n} for u, n in result.by_utility[:20]],
            "by_state": [{"state": s or "unknown", "projects": n} for s, n in result.by_state],
            "by_type": [{"type": t or "unknown", "projects": n} for t, n in result.by_type],
            "earliest_start": _iso(result.first_start),
            "latest_end": _iso(result.last_end),
            "projects": [compact(p, result.miles.get(p.id)) for p in result.projects],
        }
        if len(result.by_utility) > 20:
            payload["by_utility_note"] = f"{len(result.by_utility)} utilities; top 20 shown"
        if result.total > len(result.projects):
            payload["note"] = (f"Showing {len(result.projects)} of {result.total} matches; "
                               "the totals and breakdowns cover all of them.")
        return ToolRun(payload, result.projects, f"{result.total} projects")

    async def _details(self, conn: asyncpg.Connection, args: dict[str, Any]) -> ToolRun:
        try:
            pid = int(args.get("project_id"))
        except (TypeError, ValueError) as exc:
            raise ValueError("project_id must be an integer") from exc
        p = await repo.get_project(conn, pid)
        if p is None:
            return ToolRun({"error": f"no project with id {pid}"}, [], "not found")
        pairs = await matching.pairs_for_project(conn, pid, get_settings().default_radius_miles)
        record = {
            **compact(p),
            "source_url": p.source_url, "source_page": p.source_page,
            "excerpt": (p.raw_excerpt or "")[:600] or None,
            "extraction_confidence": round(p.confidence, 2),
            "location_is_approximate": p.approximate,
            "reviewed_by_planner": p.reviewed,
        }
        payload = {
            "project": {k: v for k, v in record.items() if v is not None},
            "coordination_pairs": [_pair(x, other_of=pid) for x in pairs[:5]],
            "coordination_pair_count": len(pairs),
        }
        others = [x.project_b if x.project_a.id == pid else x.project_a for x in pairs[:5]]
        return ToolRun(payload, [p, *others], f"project #{pid}")

    async def _overlaps(self, conn: asyncpg.Connection, args: dict[str, Any]) -> ToolRun:
        settings = get_settings()
        radius = _clamp(args.get("max_miles"), 1, 50, settings.default_radius_miles)
        limit = int(_clamp(args.get("limit"), 1, 20, 10))
        utilities: set[str] = set()
        if company := str(args.get("company") or "").strip():
            utilities = set((await search.load_companies(conn)).resolve(company))
            if not utilities:
                return ToolRun({"error": f"no company matching {company!r}"}, [], "0 pairs")
        code = None
        if state := str(args.get("state") or "").strip():
            code = search.state_code(state)
            if not code:
                raise ValueError(f"unknown US state {state!r}")

        pairs = [
            x for x in await matching.overlaps(conn, radius)
            if (not utilities or {x.project_a.utility, x.project_b.utility} & utilities)
            and (not code or _in_state(x.project_a, code) or _in_state(x.project_b, code))
        ]
        top = pairs[:limit]
        payload = {
            "total_pairs": len(pairs), "radius_miles": radius,
            "pairs": [_pair(x) for x in top],
        }
        projects = [p for x in top for p in (x.project_a, x.project_b)]
        return ToolRun(payload, projects, f"{len(pairs)} coordination pairs")

    # ------------------------------------------------------------ citations

    async def _cited(
        self, pool: asyncpg.Pool, answer: str, seen: dict[int, ProjectDTO]
    ) -> list[ProjectDTO]:
        """Projects the answer cites as [#id], in order; else the first ones looked at."""
        ids = list(dict.fromkeys(int(m) for m in re.findall(r"#(\d{1,9})\b", answer)))
        if not ids:
            return list(seen.values())[:MAX_SHOWN_PROJECTS]
        missing = [i for i in ids if i not in seen]
        if missing:
            async with pool.acquire() as conn:
                seen = {**seen, **await repo.get_projects(conn, missing)}
        return [seen[i] for i in ids if i in seen]
