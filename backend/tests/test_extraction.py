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


def test_stated_pricing_inputs_are_kept_when_sane():
    raw = {**FULL, "length_mi": 12.5, "capacity_mw": "150", "estimated_cost_musd": 42,
           "cost_year": 2025}
    p = normalize_record(raw, utility="U", page_count=1)
    assert (p.length_mi, p.capacity_mw, p.stated_cost_musd, p.cost_year) == (
        12.5, 150, 42, 2025)
    junk = {**FULL, "length_mi": -3, "capacity_mw": True, "estimated_cost_musd": "n/a",
            "cost_year": 25.5}
    p = normalize_record(junk, utility="U", page_count=1)
    assert (p.length_mi, p.capacity_mw, p.stated_cost_musd, p.cost_year) == (
        None, None, None, None)


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


# ---------------------------------------------------------------- rate limits (real filings)


def test_extraction_caps_concurrent_chunks():
    """A long filing is many chunks; only `concurrency` of them may be in flight."""
    in_flight = peak = 0

    class SlowLLM(FakeLLM):
        async def generate_json(self, prompt, schema):
            nonlocal in_flight, peak
            in_flight += 1
            peak = max(peak, in_flight)
            await asyncio.sleep(0.01)
            in_flight -= 1
            return await super().generate_json(prompt, schema)

    pages = ["x" * 50_000 for _ in range(8)]  # ~8 chunks
    doc = ParsedDocument("pdf", pages)
    asyncio.run(ExtractionService(SlowLLM(), concurrency=2).extract(doc, utility="U"))
    assert peak == 2


def test_retries_transient_errors_only():
    from app.services import llm as llm_mod

    class ApiErr(Exception):
        def __init__(self, code):
            self.code = code

    calls = {"n": 0}

    async def flaky():
        calls["n"] += 1
        if calls["n"] < 3:
            raise ApiErr(429)
        return "ok"

    assert asyncio.run(llm_mod.with_retries(flaky, attempts=5, base_delay=0)) == "ok"
    assert calls["n"] == 3

    async def bad_request():
        raise ApiErr(400)

    with pytest.raises(ApiErr):
        asyncio.run(llm_mod.with_retries(bad_request, attempts=5, base_delay=0))


# ---------------------------------------------------------------- multi-owner filings


@pytest.mark.parametrize(("owner", "expected"), [
    ("", "SERTP"),
    ("GTC", "Georgia Transmission Corp"),
    ("DEF", "Duke Energy Florida"),
    ("Duke Energy Florida, LLC", "Duke Energy Florida"),
    ("MEAG Power", "MEAG Power"),
    ("SOCO", "Southern Company"),
    ("PS", "PowerSouth"),
    ("Southern Company", "Southern Company"),
    ("DEF/SEC", "Duke Energy Florida / Seminole Electric Cooperative"),
    ("DEF-SEC", "Duke Energy Florida / Seminole Electric Cooperative"),
    ("LAK-TEC", "City of Lakeland / Tampa Electric"),
    ("Wolverine Power Supply-Coop", "Wolverine Power Supply-coop"),
])
def test_owner_overrides_plan_utility(owner, expected):
    rec = normalize_record({"name": "X", "owner": owner}, utility="SERTP", page_count=3)
    assert rec.utility == expected


def test_missing_owner_keeps_plan_utility():
    assert normalize_record({"name": "X"}, utility="JEA", page_count=1).utility == "JEA"


def test_retry_after_reads_server_hint():
    from app.services.llm import retry_after

    class Err(Exception):
        code = 429
        details = {"error": {"details": [
            {"@type": "type.googleapis.com/google.rpc.RetryInfo", "retryDelay": "40s"}]}}

    assert retry_after(Err()) == 40.0
    assert retry_after(Exception("Please retry in 12.5s.")) == 12.5
    assert retry_after(Exception("boom")) is None


def test_pacer_spaces_requests():
    import time

    from app.services.llm import RequestPacer

    async def go():
        pacer = RequestPacer(per_minute=1200)  # 50 ms apart
        start = time.monotonic()
        for _ in range(4):
            await pacer.wait()
        return time.monotonic() - start

    assert asyncio.run(go()) >= 0.14
    assert asyncio.run(_instant(RequestPacer(0))) < 0.05


async def _instant(pacer):
    import time

    start = time.monotonic()
    for _ in range(10):
        await pacer.wait()
    return time.monotonic() - start


def test_daily_quota_is_not_retried():
    from app.services import llm as llm_mod

    class Daily(Exception):
        code = 429

        def __str__(self):
            return "quotaId: GenerateRequestsPerDayPerProjectPerModel-FreeTier; retry in 53s"

    calls = {"n": 0}

    async def exhausted():
        calls["n"] += 1
        raise Daily()

    with pytest.raises(Daily):
        asyncio.run(llm_mod.with_retries(exhausted, attempts=5, base_delay=0))
    assert calls["n"] == 1
