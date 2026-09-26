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
overlapping window "{window}". It MUST propose one concrete coordination opportunity \
(for example sharing a crane or line crew, aligning outages, joint procurement, combined \
permitting or right-of-way work) that fits these two projects.

Project A ({utility_a}): {desc_a}
Project B ({utility_b}): {desc_b}
Distance apart: {miles} miles
Overlapping window (with scheduling padding): {window} ({days} days)
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
    return f"{_day(pair.window_start)} – {_day(pair.window_end)}"


def miles_text(pair: CoordinationPairDTO) -> str:
    return f"{pair.miles:.1f}"


def build_prompt(pair: CoordinationPairDTO) -> str:
    return PROMPT_TEMPLATE.format(
        miles=miles_text(pair), window=window_text(pair), days=pair.overlap_days,
        utility_a=pair.project_a.utility, desc_a=describe(pair.project_a),
        utility_b=pair.project_b.utility, desc_b=describe(pair.project_b),
    )


def facts_sentence(pair: CoordinationPairDTO) -> str:
    a, b = pair.project_a, pair.project_b
    return (
        f"{a.utility}'s {describe(a)} and {b.utility}'s {describe(b)} are "
        f"{miles_text(pair)} miles apart with overlapping work windows "
        f"({window_text(pair)})."
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

    has_facts = miles_text(pair) in text and (
        str(pair.window_start.year) in text or str(pair.window_end.year) in text
    )
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
