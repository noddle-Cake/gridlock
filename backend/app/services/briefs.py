"""Brief_Generator: a short, forwardable coordination brief per pair (Req 8)."""

from __future__ import annotations

import asyncio
import re

from app.core.errors import BriefGenerationError, BriefTimeoutError
from app.models.dto import CoordinationPairDTO, ProjectDTO
from app.services.llm import LLMClient

TIMEOUT_S = 30.0
MAX_CHARS = 600
MAX_SENTENCES = 4

PROMPT_TEMPLATE = """You are drafting a coordination note that a utility capital planner \
will forward to a planner at a neighboring utility. Write 2 to 3 plain sentences, under 450 \
characters total, no greeting, no sign-off, no bullet points, no markdown.

The note MUST state: both project types, the distance of "{miles} miles", and the \
timing "{window}". It MUST propose one concrete coordination opportunity \
(for example sharing a crane or line crew, aligning outages, joint procurement, combined \
permitting or right-of-way work) that fits these two projects.

Project A ({utility_a}): {desc_a}
Project B ({utility_b}): {desc_b}
Distance apart: {miles} miles
Timing: {window}
"""

# Sentence boundary: terminal punctuation, whitespace, then an uppercase/quote/digit start.
_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9\"'(])")


def describe(p: ProjectDTO) -> str:
    parts = []
    if p.voltage_kv:
        parts.append(f"{p.voltage_kv} kV")
    parts.append(p.type.value if p.type else "project (type unknown)")
    text = " ".join(parts)
    if p.name:
        text += f' "{p.name}"'
    if p.location_ref:
        text += f" at {p.location_ref}"
    return text


def _day(d) -> str:
    return f"{d:%b} {d.day}, {d.year}"


def window_text(pair: CoordinationPairDTO) -> str:
    """The shared build window, or how far apart the schedules are when there isn't one."""
    if pair.window_start and pair.window_end:
        return f"overlapping build window {_day(pair.window_start)} – {_day(pair.window_end)}"
    if pair.time_gap_days is not None:
        return f"in-service dates about {gap_text(pair.time_gap_days)} apart"
    return "schedule not published for one of the projects"


def gap_text(days: int) -> str:
    if days < 60:
        return f"{days} days"
    if days < 730:
        return f"{round(days / 30.4)} months"
    return f"{days / 365.25:.1f} years"


def _years(pair: CoordinationPairDTO) -> list[str]:
    """Years a brief must mention to count as stating the timing."""
    dates = [pair.window_start, pair.window_end]
    if not any(dates):
        dates = [p.end_date or p.start_date for p in (pair.project_a, pair.project_b)]
    return [str(d.year) for d in dates if d]


def miles_text(pair: CoordinationPairDTO) -> str:
    return f"{pair.miles:.1f}"


def build_prompt(pair: CoordinationPairDTO) -> str:
    return PROMPT_TEMPLATE.format(
        miles=miles_text(pair), window=window_text(pair),
        utility_a=pair.project_a.utility, desc_a=describe(pair.project_a),
        utility_b=pair.project_b.utility, desc_b=describe(pair.project_b),
    )


def facts_sentence(pair: CoordinationPairDTO) -> str:
    a, b = pair.project_a, pair.project_b
    return (
        f"{a.utility}'s {describe(a)} and {b.utility}'s {describe(b)} are "
        f"{miles_text(pair)} miles apart ({window_text(pair)})."
    )


def _sentences(text: str) -> list[str]:
    return [s.strip() for s in _SENTENCE_SPLIT.split(text) if s.strip()]


def _fit(sentences: list[str]) -> str:
    out: list[str] = []
    for s in sentences[:MAX_SENTENCES]:
        candidate = " ".join([*out, s])
        if len(candidate) > MAX_CHARS:
            break
        out.append(s)
    return " ".join(out)


def finalize_brief(raw: str, pair: CoordinationPairDTO) -> str:
    """Enforce 1-4 sentences, <= 600 chars, and the required facts (Req 8.2, 8.3).

    If the model omitted the distance/window, a deterministic facts sentence is
    prepended and the model's sentences supply the proposed opportunity (Req 8.4).
    """
    text = re.sub(r"[*_`#>]+", "", raw).replace("\n", " ")
    text = re.sub(r"\s+", " ", text).strip()
    sentences = _sentences(text)
    if not sentences:
        raise BriefGenerationError("The LLM returned an empty brief.")

    years = _years(pair)
    has_facts = miles_text(pair) in text and (not years or any(y in text for y in years))
    if not has_facts:
        # Keep the facts sentence plus as many opportunity sentences as fit.
        sentences = [facts_sentence(pair), *sentences[: MAX_SENTENCES - 1]]
    brief = _fit(sentences)
    if not brief:
        # A single sentence longer than the limit: fall back to a hard cut on a word.
        joined = " ".join(sentences)
        brief = joined[: MAX_CHARS - 1].rsplit(" ", 1)[0].rstrip(",;:.") + "."
    return brief


class BriefGenerator:
    def __init__(self, llm: LLMClient, *, timeout: float = TIMEOUT_S) -> None:
        self._llm = llm
        self._timeout = timeout

    async def generate(self, pair: CoordinationPairDTO) -> str:
        """Never returns a partial brief: timeout -> BriefTimeoutError (Req 8.6), any other
        failure -> BriefGenerationError (Req 8.7)."""
        try:
            raw = await asyncio.wait_for(
                self._llm.generate_text(build_prompt(pair)), timeout=self._timeout
            )
        except TimeoutError as exc:
            raise BriefTimeoutError(
                f"Brief generation timed out after {int(self._timeout)} seconds."
            ) from exc
        except Exception as exc:
            raise BriefGenerationError(f"Brief generation failed: {exc}") from exc
        return finalize_brief(raw, pair)
