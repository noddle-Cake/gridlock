import asyncio
from datetime import date

import pytest
from hypothesis import given
from hypothesis import strategies as st

from app.core.errors import BriefGenerationError, BriefTimeoutError
from app.models.dto import CoordinationPairDTO, ProjectDTO, ScoreFactorsDTO
from app.models.enums import ProjectType
from app.services.briefs import MAX_CHARS, MAX_SENTENCES, BriefGenerator, _sentences, finalize_brief
from tests.conftest import FakeLLM


def make_pair() -> CoordinationPairDTO:
    a = ProjectDTO(id=1, utility="Met-Ed", name="Hanover breaker replacement",
                   type=ProjectType.SUBSTATION, voltage_kv=138, confidence=0.9,
                   location_ref="Hanover, PA")
    b = ProjectDTO(id=2, utility="BGE", name="Westminster breaker upgrade",
                   type=ProjectType.SUBSTATION, voltage_kv=115, confidence=0.8,
                   location_ref="Westminster, MD")
    return CoordinationPairDTO(
        id="1-2", project_a=a, project_b=b, miles=12.34, overlap_days=92,
        window_start=date(2026, 4, 1), window_end=date(2026, 7, 1),
        scores=ScoreFactorsDTO(distance=0.5, overlap=0.25, type_similarity=1,
                               voltage_similarity=0.95, composite=0.6),
    )


def test_prompt_contains_required_facts():
    llm = FakeLLM(brief="Both utilities could share a crane crew. Contact us.")
    text = asyncio.run(BriefGenerator(llm).generate(make_pair()))
    prompt = llm.prompts[0]
    assert "substation" in prompt and "12.3 miles" in prompt
    assert "Apr 1, 2026" in prompt and "Jul 1, 2026" in prompt
    # The model omitted the facts, so the deterministic facts sentence was prepended.
    assert "12.3 miles" in text and "substation" in text and "2026" in text
    assert "crane" in text


def test_no_shared_window_states_the_gap():
    pair = make_pair()
    pair.project_a.end_date = date(2026, 6, 1)
    pair.project_b.end_date = date(2033, 6, 1)
    pair.window_start = pair.window_end = None
    pair.overlap_days, pair.time_gap_days = 0, 2557
    llm = FakeLLM(brief="Both utilities could share a line crew.")
    text = asyncio.run(BriefGenerator(llm).generate(pair))
    assert "in-service dates about 7.0 years apart" in llm.prompts[0]
    assert "12.3 miles" in text and "7.0 years" in text


def test_model_brief_with_facts_kept_verbatim():
    brief = ("Met-Ed's 138 kV substation work at Hanover and BGE's 115 kV substation upgrade "
             "at Westminster are 12.3 miles apart and overlap Apr 1, 2026 – Jul 1, 2026. "
             "We propose sharing one crane crew across both sites.")
    text = asyncio.run(BriefGenerator(FakeLLM(brief=brief)).generate(make_pair()))
    assert text == brief


@given(st.text(min_size=1, max_size=3000))
def test_brief_always_within_limits(raw):
    try:
        text = finalize_brief(raw, make_pair())
    except BriefGenerationError:
        return  # empty/whitespace model output is a failure, never a partial brief
    assert 1 <= len(_sentences(text)) <= MAX_SENTENCES
    assert len(text) <= MAX_CHARS
    assert "12.3" in text


def test_timeout_returns_error_not_partial():
    gen = BriefGenerator(FakeLLM(delay=1.0), timeout=0.05)
    with pytest.raises(BriefTimeoutError, match="timed out"):
        asyncio.run(gen.generate(make_pair()))


def test_other_failure_is_identified():
    with pytest.raises(BriefGenerationError, match="model unavailable"):
        asyncio.run(BriefGenerator(FakeLLM(fail=True)).generate(make_pair()))
