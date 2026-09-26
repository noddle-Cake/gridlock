"""Extraction_Service: Gemini structured extraction + a pure normalizer (Req 2, 3)."""

from __future__ import annotations

import asyncio
import json
import math
from dataclasses import dataclass
from typing import Any

from app.core.config import get_settings
from app.core.errors import ExtractionFailedError
from app.models.enums import ProjectType
from app.models.partial_date import PartialDate
from app.services.llm import LLMClient
from app.services.owners import canonical_utility
from app.services.parsing import ParsedDocument

MAX_EXCERPT_CHARS = 2000
MIN_KV, MAX_KV = 0.1, 2000.0
# ~15k chars is ~50 dense table rows: each row comes back with its verbatim excerpt, and a
# bigger chunk from a project-list filing (SERTP: ~290 rows) overruns the output limit.
CHUNK_CHARS = 15_000
# Confidence = blend of model self-reported certainty and field completeness.
CERTAINTY_WEIGHT = 0.6
COMPLETENESS_FIELDS = ("name", "type", "voltage_kv", "location_ref", "start_date", "end_date")


@dataclass
class ExtractedProject:
    utility: str
    confidence: float
    name: str = ""
    state: str = ""
    type: ProjectType | None = None
    voltage_kv: float | None = None
    location_ref: str = ""
    location_kind: str = ""  # substation | town | county | "" (hint for the geocoder)
    start_date: PartialDate | None = None
    end_date: PartialDate | None = None
    source_page: int | None = None
    raw_excerpt: str = ""
    reviewed: bool = False


# JSON schema handed to Gemini (structured output). Mirrors ExtractedProject.
RESPONSE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "projects": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "owner": {"type": "string"},
                    "type": {
                        "type": "string",
                        "enum": ["substation", "transmission line", "generation", ""],
                    },
                    "voltage_kv": {"type": ["number", "null"]},
                    "location_ref": {"type": "string"},
                    "location_kind": {
                        "type": "string", "enum": ["substation", "town", "county", ""],
                    },
                    "state": {"type": "string"},
                    "start_date": {"type": "string"},
                    "end_date": {"type": "string"},
                    "source_page": {"type": "integer"},
                    "raw_excerpt": {"type": "string"},
                    "certainty": {"type": "number"},
                },
                "required": [
                    "name", "owner", "type", "voltage_kv", "location_ref", "location_kind", "state",
                    "start_date", "end_date", "source_page", "raw_excerpt", "certainty",
                ],
            },
        }
    },
    "required": ["projects"],
}

PROMPT_TEMPLATE = """You extract planned capital projects from an electric utility's public \
capital plan. The document is from the utility "{utility}". It is split into pages marked \
"=== PAGE n ===" (pages {first}-{last} of {total} shown here).

Return every distinct planned capital project (substations, transmission lines, generation) \
as one entry. Rules:
- Use ONLY information stated in the text. If a field cannot be determined, use an empty \
string ("" or null for voltage_kv). Never guess.
- owner: the company that owns THIS project when the document covers several owners \
(an owner column, or a prefix such as "GTC:" or "MEAG:"). Expand abbreviations with the \
document's own legend when it has one (e.g. "DEF" -> "Duke Energy Florida"); otherwise \
copy the abbreviation as written. Use "" when the project belongs to "{utility}" itself.
- type: exactly "substation", "transmission line", or "generation"; "" if it fits none.
- voltage_kv: a number in kilovolts (e.g. "138kV" -> 138, "345 kV" -> 345). null if absent.
- location_ref: the most specific place named: a substation name, town, or county, plus the \
state if given (e.g. "Hanover Substation, PA", "Adams County, PA", "Gettysburg, PA").
- location_kind: "substation", "town", or "county" describing location_ref; "" if none.
- state: two-letter US state if determinable, else "".
- start_date / end_date: keep the source precision. Use "YYYY" for a year, "Q2 YYYY" for a \
quarter, "YYYY-MM" for a month, "YYYY-MM-DD" for a day. Never invent a finer precision.
- source_page: the page number (from the PAGE markers) where the project appears.
- raw_excerpt: the verbatim source text the project was read from (max 2000 characters).
- certainty: your confidence from 0.0 to 1.0 that this entry is a real project and its \
fields are correct.

Document:
{body}
"""


def _chunks(doc: ParsedDocument) -> list[tuple[int, int, str]]:
    """Group pages into ~CHUNK_CHARS prompts; oversized pages are split on line breaks."""
    segments: list[tuple[int, str]] = []
    for page_no, text in enumerate(doc.pages, start=1):
        if not text:
            continue
        if len(text) <= CHUNK_CHARS:
            segments.append((page_no, text))
            continue
        part: list[str] = []
        size = 0
        for line in text.splitlines():
            if size + len(line) > CHUNK_CHARS and part:
                segments.append((page_no, "\n".join(part)))
                part, size = [], 0
            part.append(line)
            size += len(line) + 1
        if part:
            segments.append((page_no, "\n".join(part)))

    chunks: list[tuple[int, int, str]] = []
    current: list[tuple[int, str]] = []
    size = 0
    for page_no, text in segments:
        if current and size + len(text) > CHUNK_CHARS:
            chunks.append(_render(current))
            current, size = [], 0
        current.append((page_no, text))
        size += len(text)
    if current:
        chunks.append(_render(current))
    return chunks


def _render(segments: list[tuple[int, str]]) -> tuple[int, int, str]:
    body = "\n\n".join(f"=== PAGE {p} ===\n{t}" for p, t in segments)
    return segments[0][0], segments[-1][0], body


# ---------------------------------------------------------------- normalizer


def _text(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _number(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, str):
        cleaned = value.lower().replace("kv", "").replace(",", "").strip()
        try:
            value = float(cleaned)
        except ValueError:
            return None
    if isinstance(value, (int, float)) and math.isfinite(value):
        return float(value)
    return None


def normalize_record(
    raw: Any, *, utility: str, page_count: int
) -> ExtractedProject:
    """Turn one raw model record into an ExtractedProject that satisfies the schema
    invariants (Property 11). Undeterminable fields become empty; the record is still
    created (Property 12)."""
    if not isinstance(raw, dict):
        raw = {}

    voltage = _number(raw.get("voltage_kv"))
    if voltage is not None and not (MIN_KV <= voltage <= MAX_KV):
        voltage = None

    page = raw.get("source_page")
    page = int(page) if isinstance(page, (int, float)) and not isinstance(page, bool) and (
        math.isfinite(page) and float(page).is_integer()) else None
    if page is not None and not (1 <= page <= page_count):
        page = None
    if page is None and page_count == 1:
        page = 1

    kind = _text(raw.get("location_kind")).lower()
    state = _text(raw.get("state")).upper()
    record = ExtractedProject(
        # Multi-owner filings (SERTP, FRCC tables) name an owner per project.
        utility=canonical_utility(_text(raw.get("owner"))) or utility,
        confidence=0.0,
        name=_text(raw.get("name")),
        state=state if len(state) == 2 and state.isalpha() else "",
        type=ProjectType.coerce(raw.get("type")),
        voltage_kv=voltage,
        location_ref=_text(raw.get("location_ref")),
        location_kind=kind if kind in ("substation", "town", "county") else "",
        start_date=PartialDate.parse(raw.get("start_date")),
        end_date=PartialDate.parse(raw.get("end_date")),
        source_page=page,
        raw_excerpt=_text(raw.get("raw_excerpt"))[:MAX_EXCERPT_CHARS],
        reviewed=False,
    )
    # A reversed range is not trustworthy: keep the start, drop the end.
    if record.start_date and record.end_date and (
        record.start_date.materialize()[0] > record.end_date.materialize()[1]
    ):
        record.end_date = None

    certainty = _number(raw.get("certainty"))
    certainty = 0.5 if certainty is None else max(0.0, min(1.0, certainty))
    filled = sum(1 for f in COMPLETENESS_FIELDS if getattr(record, f) not in ("", None))
    completeness = filled / len(COMPLETENESS_FIELDS)
    confidence = CERTAINTY_WEIGHT * certainty + (1 - CERTAINTY_WEIGHT) * completeness
    record.confidence = round(max(0.0, min(1.0, confidence)), 4)
    return record


def parse_model_output(text: str, *, utility: str, page_count: int) -> list[ExtractedProject]:
    data = json.loads(text)
    items = data.get("projects") if isinstance(data, dict) else data
    if not isinstance(items, list):
        raise ValueError("model output has no project list")
    return [normalize_record(item, utility=utility, page_count=page_count) for item in items]


# ---------------------------------------------------------------- service


class ExtractionService:
    def __init__(self, llm: LLMClient, *, concurrency: int | None = None) -> None:
        self._llm = llm
        # Real filings run to hundreds of pages (dozens of chunks); firing them all at
        # once trips the Gemini rate limit and, all-or-nothing, fails the whole plan.
        self._concurrency = max(1, concurrency or get_settings().extraction_concurrency)

    async def extract(self, doc: ParsedDocument, *, utility: str) -> list[ExtractedProject]:
        """All-or-nothing: any failed chunk fails the whole document (Req 2.9)."""
        chunks = _chunks(doc)
        if not chunks:
            raise ExtractionFailedError("Extraction failed: the document has no text.")
        limit = asyncio.Semaphore(self._concurrency)

        async def run(first: int, last: int, body: str) -> list[ExtractedProject]:
            prompt = PROMPT_TEMPLATE.format(
                utility=utility, first=first, last=last, total=doc.page_count, body=body
            )
            async with limit:
                text = await self._llm.generate_json(prompt, RESPONSE_SCHEMA)
            return parse_model_output(text, utility=utility, page_count=doc.page_count)

        try:
            results = await asyncio.gather(*(run(*c) for c in chunks))
        except ExtractionFailedError:
            raise
        except Exception as exc:
            raise ExtractionFailedError(f"Extraction failed: {exc}") from exc
        return [p for batch in results for p in batch]
