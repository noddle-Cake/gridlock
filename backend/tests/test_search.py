"""Search bar (GET /search) and Ask GridMerge (POST /ask)."""

from __future__ import annotations

import asyncio
import json
import re
from datetime import date

import pytest

from app.core.errors import AskTimeoutError, AskUnavailableError
from app.db import repository as repo
from app.models.enums import DatePrecision, ProjectType
from app.services.ask import AskService
from app.services.llm import AgentTurn, ToolCall, UnconfiguredClient
from app.services.search import (
    CompanyIndex,
    looks_like_question,
    parse_query,
    state_code,
    zip_centroid,
)
from tests.conftest import FakeLLM
from tests.test_api import seed

COMPANIES = CompanyIndex.build({
    "Florida Power & Light": 13, "Duke Energy Florida": 4, "Duke Energy Carolinas": 67,
    "Georgia Transmission Corp": 67, "Southern Company": 204, "TVA": 57, "MEAG Power": 12,
})


def parse(q: str):
    return parse_query(q, COMPANIES)


# ---------------------------------------------------------------- parsing (no DB)


@pytest.mark.parametrize("q", ["FPL", "fpl", "Florida Power & Light", "florida power and light",
                               "Florida Power", "FPL's"])
def test_company_names_and_acronyms(q):
    p = parse(q)
    assert p.utilities == ["Florida Power & Light"]
    assert p.states == [] and p.terms == []


def test_state_names_and_codes():
    assert parse("Florida").states == ["FL"]
    assert parse("FL").states == ["FL"]
    assert parse("fl").states == ["FL"]
    assert parse("new york solar").states == ["NY"]
    assert parse("new york solar").terms == ["solar"]
    assert state_code("Georgia") == state_code("ga") == "GA"
    assert state_code("Narnia") is None


def test_everyday_two_letter_words_are_not_states():
    assert parse("TVA projects in Tennessee").states == ["TN"]
    assert parse("solar or wind").states == []
    assert parse("FPL projects in OR").states == ["OR"]  # typed in capitals: Oregon
    assert parse("in").states == ["IN"]  # the whole query: Indiana


def test_zip_code_with_company():
    p = parse("FPL 33101")
    assert p.zip == "33101" and p.utilities == ["Florida Power & Light"]
    assert parse("33157-1234").zip == "33157"


def test_state_and_type_words_are_not_a_company():
    p = parse("Georgia transmission projects")
    assert p.utilities == []
    assert p.states == ["GA"] and p.types == [ProjectType.TRANSMISSION_LINE]
    # The full company name still wins over the state it contains.
    assert parse("Georgia Transmission Corp").utilities == ["Georgia Transmission Corp"]


def test_company_prefix_while_typing():
    assert parse("florida pow").utilities == ["Florida Power & Light"]
    assert sorted(parse("duke energy").utilities) == ["Duke Energy Carolinas",
                                                      "Duke Energy Florida"]
    assert parse("TVA substations").types == [ProjectType.SUBSTATION]


def test_company_suggestions():
    assert COMPANIES.suggest("Florida", [], 5) == ["Florida Power & Light",
                                                   "Duke Energy Florida"]
    assert COMPANIES.suggest("geor", [], 5) == ["Georgia Transmission Corp"]
    assert COMPANIES.suggest("florda powr", [], 5) == ["Florida Power & Light"]  # typo
    assert COMPANIES.suggest("florda powr", [], 5, typos=False) == []
    assert COMPANIES.suggest("fl", [], 5) == []  # too short to guess from


def test_question_detection():
    assert looks_like_question("Which utilities have projects in Georgia?")
    assert looks_like_question("how many substations does TVA plan")
    assert not looks_like_question("FPL projects in Georgia")
    assert not looks_like_question("Georgia")


def test_zip_gazetteer():
    lat, lng = zip_centroid("33157")
    assert 25 < lat < 26 and -81 < lng < -80
    assert zip_centroid("99999") is None


def test_state_ref_pattern_reads_location_suffixes():
    pattern = repo.state_ref_pattern(["GA"])
    assert re.search(pattern, "Thomas County, GA")
    assert re.search(pattern, "Valdosta - Lake Park 230 kV (GA/FL)")
    assert not re.search(pattern, "GAINESVILLE, FL")


# ---------------------------------------------------------------- GET /search (DB)

SRC = "https://example.com/plan.pdf"


def _project(utility, name, type_, lat, lng, state, location=None, **kw):
    return repo.NewProject(
        utility=utility, name=name, type=type_, lat=lat, lng=lng, state=state,
        location_ref=location or name, confidence=0.9, source_url=SRC,
        start_date=date(2027, 1, 1), end_date=date(2028, 6, 30), **kw,
    )


def seed_region() -> dict[str, int]:
    ids = seed([
        _project("Florida Power & Light", "Turkey Point solar", ProjectType.GENERATION,
                 25.70, -80.40, "FL"),
        _project("Florida Power & Light", "Tallahassee tie line", ProjectType.TRANSMISSION_LINE,
                 30.44, -84.28, "FL"),
        _project("Georgia Transmission Corp", "Thomasville - Boston 115 kV",
                 ProjectType.TRANSMISSION_LINE, 30.83, -83.98, "GA"),
        _project("Southern Company", "Valdosta - Lake Park 230 kV",
                 ProjectType.TRANSMISSION_LINE, 30.83, -83.60, None,
                 location="Valdosta - Lake Park 230 kV (GA/FL)"),
        _project("Duke Energy Florida", "Orlando substation", ProjectType.SUBSTATION,
                 28.54, -81.38, "FL"),
    ])
    return dict(zip(["fpl_miami", "fpl_tally", "gtc", "southern", "duke"], ids, strict=True))


def search(client, q, **params):
    r = client.get("/search", params={"q": q, **params})
    assert r.status_code == 200, r.text
    return r.json()


def test_search_by_company(api_client):
    ids = seed_region()
    for q in ("FPL", "Florida Power & Light"):
        body = search(api_client, q)
        assert body["interpretation"]["utilities"] == ["Florida Power & Light"]
        assert sorted(body["project_ids"]) == sorted([ids["fpl_miami"], ids["fpl_tally"]])
        assert body["companies"][0] == {"utility": "Florida Power & Light", "project_count": 2}
        assert body["suggest_ai"] is False


def test_search_by_state_reads_location_when_state_is_missing(api_client):
    ids = seed_region()
    body = search(api_client, "Georgia")
    assert body["interpretation"]["states"] == ["GA"]
    # Southern Company's row has no state column, only "(GA/FL)" in its location.
    assert sorted(body["project_ids"]) == sorted([ids["gtc"], ids["southern"]])
    assert body["locations"] == [
        {"kind": "state", "code": "GA", "label": "Georgia", "project_count": 2}
    ]
    assert len(search(api_client, "FL")["project_ids"]) == 4


def test_search_state_and_type(api_client):
    ids = seed_region()
    body = search(api_client, "Florida transmission projects")
    assert body["interpretation"]["types"] == ["transmission line"]
    assert sorted(body["project_ids"]) == sorted([ids["fpl_tally"], ids["southern"]])


def test_search_by_zip_code(api_client):
    ids = seed_region()
    body = search(api_client, "33157")
    assert body["project_ids"] == [ids["fpl_miami"]]
    assert body["interpretation"]["zip_found"] is True
    assert body["interpretation"]["radius_miles"] == 25
    assert body["interpretation"]["zip_label"].startswith("ZIP 33157 · near Miami-Dade")
    assert 0 < body["projects"][0]["miles"] < 25
    south, west, north, east = body["bounds"]
    assert south <= 25.70 <= north and west <= -80.40 <= east


def test_search_company_and_zip(api_client):
    ids = seed_region()
    assert search(api_client, "FPL 32301")["project_ids"] == [ids["fpl_tally"]]
    assert search(api_client, "Duke 32301")["project_ids"] == []


def test_zip_search_widens_its_radius(api_client):
    ids = seed_region()
    body = search(api_client, "33440")  # ~70 miles from the nearest project
    assert body["project_ids"] == [ids["fpl_miami"]]
    assert body["interpretation"]["radius_miles"] == 100
    assert body["locations"][0]["label"].endswith("· 100 mi")
    assert search(api_client, "33901")["total"] == 0  # nothing within 100 miles


def test_unknown_zip_is_reported_not_guessed(api_client):
    seed_region()
    body = search(api_client, "99999")
    assert body["interpretation"]["zip_found"] is False
    assert body["total"] == 0


def test_typo_falls_back_to_trigram_match(api_client):
    ids = seed_region()
    body = search(api_client, "Florda Powr")
    assert body["interpretation"]["fuzzy"] is True
    assert sorted(body["project_ids"]) == sorted([ids["fpl_miami"], ids["fpl_tally"]])


def test_search_text_and_limit(api_client):
    ids = seed_region()
    body = search(api_client, "thomasville")
    assert body["project_ids"] == [ids["gtc"]]
    body = search(api_client, "FL", limit=1)
    assert len(body["projects"]) == 1 and body["total"] == 4


def test_search_leaves_out_finished_projects(api_client):
    """Search lists work not yet in service, like the map and Review (PLANNING_FROM is pinned
    to 2026-01-01 in tests). A year-only date runs to Dec 31; undated work stays findable."""
    def fpl(name, start=None, end=None, precision=None):
        return repo.NewProject(
            utility="Florida Power & Light", name=name, lat=27.0, lng=-81.0, state="FL",
            confidence=0.9, source_url=SRC, start_date=start, end_date=end,
            start_precision=precision, end_precision=precision,
        )

    ids = seed([
        fpl("Ahead", date(2027, 1, 1), date(2028, 6, 30)),
        fpl("Done", date(2024, 1, 1), date(2025, 6, 30)),
        fpl("Undated"),
        fpl("Year 2025", date(2025, 1, 1), date(2025, 1, 1), DatePrecision.YEAR),
        fpl("Year 2026", date(2026, 1, 1), date(2026, 1, 1), DatePrecision.YEAR),
    ])
    body = search(api_client, "FPL")
    assert sorted(body["project_ids"]) == [ids[0], ids[2], ids[4]]


def test_question_suggests_ai_and_empty_query(api_client):
    seed_region()
    body = search(api_client, "Which utilities have projects in Georgia?")
    assert body["suggest_ai"] is True
    assert body["total"] == 2
    empty = search(api_client, "  ")
    assert empty["total"] == 0 and empty["projects"] == []


# ---------------------------------------------------------------- POST /ask


def test_ask_runs_tools_and_cites_projects(api_client):
    ids = seed_region()
    api_client.llm.turns = [
        AgentTurn(calls=[ToolCall("c1", "search_gridmerge",
                                  {"state": "Georgia", "type": "transmission line"})],
                  text="", handle="i1"),
        AgentTurn(calls=[], handle="i2",
                  text=f"Two utilities: **Georgia Transmission Corp** [#{ids['gtc']}] and "
                       f"**Southern Company** [#{ids['southern']}]."),
    ]
    r = api_client.post("/ask", json={"question": "Which utilities build lines in Georgia?"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert "Georgia Transmission Corp" in body["answer"]
    assert [p["id"] for p in body["projects"]] == [ids["gtc"], ids["southern"]]
    assert body["tool_calls"] == [{
        "name": "search_gridmerge", "summary": "2 projects",
        "arguments": {"state": "Georgia", "type": "transmission line"},
    }]

    first, second = api_client.llm.conversation
    assert first["message"] == "Which utilities build lines in Georgia?"
    assert {t["name"] for t in first["tools"]} == {
        "search_gridmerge", "get_project_details", "find_coordination_overlaps"}
    assert second["previous"] == "i1"
    [result] = second["results"]
    payload = json.loads(result.result)
    assert result.call_id == "c1" and not result.is_error
    assert payload["total_matches"] == 2
    assert payload["filters"]["states"] == ["GA"]
    assert {u["utility"] for u in payload["by_utility"]} == {"Georgia Transmission Corp",
                                                            "Southern Company"}


def test_ask_project_details_and_overlaps_tools(api_client):
    ids = seed_region()
    api_client.llm.turns = [
        AgentTurn(calls=[
            ToolCall("c1", "get_project_details", {"project_id": ids["gtc"]}),
            ToolCall("c2", "find_coordination_overlaps", {"company": "GTC", "max_miles": 50}),
        ], text="", handle="i1"),
        AgentTurn(calls=[], text="Thomasville pairs with Valdosta.", handle="i2"),
    ]
    body = api_client.post("/ask", json={"question": "What overlaps with GTC?"}).json()
    details, overlaps = (json.loads(r.result) for r in api_client.llm.conversation[1]["results"])
    assert details["project"]["name"] == "Thomasville - Boston 115 kV"
    assert details["coordination_pair_count"] >= 1
    assert overlaps["total_pairs"] >= 1
    assert overlaps["pairs"][0]["project_a"]["id"] in (ids["gtc"], ids["southern"])
    # No citations in the answer: the projects the tools looked at come back instead.
    assert ids["gtc"] in [p["id"] for p in body["projects"]]


def test_ask_reports_bad_tool_calls_to_the_model(api_client):
    seed_region()
    api_client.llm.turns = [
        AgentTurn(calls=[ToolCall("c1", "drop_tables", {}),
                         ToolCall("c2", "search_gridmerge", {"state": "Narnia"})],
                  text="", handle="i1"),
        AgentTurn(calls=[], text="I could not search that.", handle="i2"),
    ]
    r = api_client.post("/ask", json={"question": "Projects in Narnia?"})
    assert r.status_code == 200
    results = api_client.llm.conversation[1]["results"]
    assert all(x.is_error for x in results)
    assert "Narnia" in results[1].result


def test_ask_stops_after_the_tool_budget(api_client):
    seed_region()
    api_client.llm.turns = [
        AgentTurn(calls=[ToolCall(f"c{i}", "search_gridmerge", {"query": "solar"})],
                  text="", handle=f"i{i}")
        for i in range(10)
    ]
    r = api_client.post("/ask", json={"question": "loop forever"})
    # Four rounds of tools, then one round told to answer; the model never does.
    assert len(api_client.llm.conversation) == 6
    assert all(x.is_error for x in api_client.llm.conversation[-1]["results"])
    assert r.status_code == 502 and r.json()["error"]["code"] == "ask_failed"


def test_ask_validates_the_question(api_client):
    assert api_client.post("/ask", json={"question": ""}).status_code == 422
    assert api_client.post("/ask", json={"question": "x" * 501}).status_code == 422


def test_ask_without_api_key_is_503():
    with pytest.raises(AskUnavailableError, match="GEMINI_API_KEY"):
        asyncio.run(AskService(UnconfiguredClient()).ask(None, "hi"))  # type: ignore[arg-type]
    assert AskUnavailableError.status_code == 503


def test_ask_times_out():
    service = AskService(FakeLLM(delay=1.0), timeout=0.05)
    with pytest.raises(AskTimeoutError):
        asyncio.run(service.ask(None, "hi"))  # type: ignore[arg-type]
