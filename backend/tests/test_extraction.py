import asyncio
import json

import pytest
from hypothesis import given
from hypothesis import strategies as st

from app.core.errors import ExtractionFailedError
from app.models.enums import ProjectType
from app.services.extraction import (
    COMPLETENESS_FIELDS,
    MAX_EXCERPT_CHARS,
    ExtractionService,
    normalize_record,
)
from app.services.parsing import ParsedDocument
from tests.conftest import FakeLLM

junk = st.one_of(
    st.none(), st.text(max_size=30), st.integers(-10_000, 10_000),
    st.floats(allow_nan=True, allow_infinity=True), st.booleans(),
)

raw_records = st.fixed_dictionaries(
    {},
    optional={
        "name": st.one_of(junk, st.text(max_size=80)),
        "type": st.one_of(junk, st.sampled_from(["substation", "transmission line",
                                                 "generation", "Substation", "battery", ""])),
        "voltage_kv": st.one_of(junk, st.floats(-10, 5000), st.sampled_from(["138kV", "69"])),
        "location_ref": st.one_of(junk, st.text(max_size=60)),
        "state": st.one_of(junk, st.sampled_from(["PA", "md", "Pennsylvania", ""])),
        "start_date": st.one_of(junk, st.sampled_from(["2026", "Q3 2027", "2026-05", "bogus"])),
        "end_date": st.one_of(junk, st.sampled_from(["2028", "Q1 2029", "2029-02-14", ""])),
        "source_page": junk,
        "raw_excerpt": st.one_of(junk, st.text(max_size=3000)),
        "certainty": junk,
    },
)


# Feature: gridmerge, Property 11: Accepted extracted record satisfies schema invariants
@given(raw_records, st.integers(1, 500))
def test_record_invariants(raw, page_count):
    p = normalize_record(raw, utility="Util A", page_count=page_count)
    assert 0.0 <= p.confidence <= 1.0
    assert p.source_page is None or (
        isinstance(p.source_page, int) and 1 <= p.source_page <= page_count
    )
    assert len(p.raw_excerpt) <= MAX_EXCERPT_CHARS
    assert p.type is None or isinstance(p.type, ProjectType)
    assert p.voltage_kv is None or 0.1 <= p.voltage_kv <= 2000
    assert p.reviewed is False  # Req 3.2
    assert p.utility == "Util A"


FULL = {
    "name": "Hanover 138kV breaker replacement",
    "type": "substation",
    "voltage_kv": 138,
    "location_ref": "Hanover Substation, PA",
    "start_date": "Q2 2026",
    "end_date": "Q4 2026",
    "raw_excerpt": "Replace 138kV breakers at Hanover Substation, Q2-Q4 2026.",
}


# Feature: gridmerge, Property 12: Undeterminable fields are emptied, record still created
@given(st.sets(st.sampled_from(list(FULL))), st.booleans())
def test_undeterminable_fields_emptied(unknown, unclassifiable_type):
    raw = {k: ("" if k in unknown else v) for k, v in FULL.items()}
    if unclassifiable_type:
        raw["type"] = "battery storage"
    p = normalize_record(raw, utility="Util A", page_count=3)

    assert p is not None
    for field in FULL:
        value = getattr(p, field)
        if field in unknown or (field == "type" and unclassifiable_type):
            assert value in ("", None), field
        else:
            assert value not in ("", None), field
    if "voltage_kv" not in unknown:
        assert p.voltage_kv == 138


def test_confidence_rewards_completeness():
    full = normalize_record({**FULL, "certainty": 0.9}, utility="U", page_count=1)
    sparse = normalize_record({"name": "x", "certainty": 0.9}, utility="U", page_count=1)
    assert full.confidence > sparse.confidence
    assert len(COMPLETENESS_FIELDS) == 6


def test_whole_document_failure_creates_nothing():
    """Req 2.9 at the service level: a failing chunk fails the whole document."""
    doc = ParsedDocument("pdf", ["page one text", "page two text"])
    service = ExtractionService(FakeLLM(fail=True))
    with pytest.raises(ExtractionFailedError, match="Extraction failed"):
        asyncio.run(service.extract(doc, utility="Util A"))


def test_extract_parses_model_output():
    llm = FakeLLM(projects=[{**FULL, "source_page": 2, "certainty": 0.8}])
    doc = ParsedDocument("pdf", ["intro", "projects page"])
    projects = asyncio.run(ExtractionService(llm).extract(doc, utility="Util A"))
    assert len(projects) == 1
    assert projects[0].source_page == 2
    assert "=== PAGE 2 ===" in llm.prompts[0]
    assert json.loads(json.dumps(projects[0].name))
