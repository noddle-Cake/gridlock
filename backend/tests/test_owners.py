"""Corporate-family exclusions apply to existing rows and every matching entry point."""

from datetime import UTC, date, datetime
from unittest.mock import AsyncMock

import pytest

from app.db import repository as repo
from app.models.dto import ProjectDTO
from app.services import matching
from app.services.owners import different_companies, ownership_review_required


@pytest.mark.parametrize(("a", "b"), [
    ("FRP Forest Trail Solar, LLC", "Frp Miller Solar"),
    ("FRP Miller Solar", "FPL"),
    ("FRP Forest Trail Solar", "NextEra Energy Resources, LLC"),
    ("FRP", "Florida Renewable Partners, LLC"),
    ("Florida Renewable Partners", "Florida Power & Light Company"),
    ("FPL", " Florida Power and Light Co. "),
    ("Gulf Power", "FPL"),
    ("georgia power co.", "Southern Company"),
    ("Alabama Power", "Georgia Power"),
    ("Southern Power", "Georgia Power"),
    ("Duke Energy Progress - (SC)", "DEF"),
    ("Duke Energy Carolinas", "Duke Energy Florida, LLC"),
    ("DESC", "Dominion Energy"),
    ("SCANA Corporation", "Dominion Energy South Carolina"),
    ("DEF/SEC", "DEF"),
    ("DEF-SEC", "SEC / FPL"),
    ("FPL / JEA", "FRP Miller Solar"),
    ("Example Utility, L.L.C.", "example utility"),
    ("UNKNOWN", "Georgia Power"),
    ("Utility A", "Utility B"),
    ("SR Bacon LLC", "SR Bacon III LLC"),
    ("Juniper Solar", "B & K Solar"),
    ("Kingstree East 230", "Kingstree West 115"),
    ("Placid Solar", "Placid Solar II"),
    ("", "FPL"),
    # Withheld by the ownership audit (status review), whoever the other company is.
    ("Alligator Creek Solar", "Georgia Power"),
    # Unreviewed names that read as one developer's projects.
    ("Atlas Solar IV", "Atlas BESS IV"),
    ("Lazy U Solar 1", "Lazy U ESS 2"),
    ("Bridgewater Solar", "Bridgewater Solar 2"),
    ("Cp Tully Four", "Cp Tully Five"),
    ("Evergy Kansas Central", "Evergy Missouri West"),
    ("Cve Us Pa Dayton 404", "Cve Us Pa Kittanning 406"),
    ("Solar 1", "Solar 2"),
])
def test_related_or_unknown_companies_do_not_match(a, b):
    assert not different_companies(a, b)
    assert not different_companies(b, a)


@pytest.mark.parametrize(("a", "b"), [
    ("Dominion Energy South Carolina", "Georgia Power"),
    ("DESC", "GAPC"),
    ("FRP Miller Solar", "Duke Energy Florida"),
    ("FRP Forest Trail Solar", "JEA"),
    ("FRP", "Seminole Electric Cooperative"),  # power purchases aren't ownership
    ("DEF/SEC", "FPL"),
])
def test_different_companies_remain_eligible(a, b):
    assert different_companies(a, b)
    assert different_companies(b, a)


@pytest.mark.parametrize(("a", "b"), [
    ("FRP Holdings", "FPL"),  # not NextEra's FRP solar LLCs
    ("FRPower Solar", "FPL"),
    ("Pivot Energy", "Prologis Logistics Services Incorporated"),
    ("Big Creek Solar", "Big Sky Wind"),  # a generic first word isn't a developer
    ("Unreviewed project LLC", "JEA"),
])
def test_unreviewed_companies_match_but_stay_flagged(a, b):
    assert different_companies(a, b)
    assert different_companies(b, a)
    assert ownership_review_required(a) or ownership_review_required(b)


@pytest.mark.parametrize("entry", ["overlaps", "find_pair", "pairs_for_project", "rematch_project"])
@pytest.mark.parametrize(("owner", "eligible"), [
    ("FRP Forest Trail Solar, LLC", False),
    ("Florida Power & Light", False),
    ("JEA", True),
    ("Unreviewed project LLC", True),  # shown, labelled ownership unverified
])
async def test_matching_entry_points_filter_stored_company_names(
    monkeypatch, entry, owner, eligible,
):
    projects = {
        1: ProjectDTO(id=1, utility="Frp Miller Solar", confidence=1,
                      start_date=date(2027, 1, 1), end_date=date(2027, 12, 31)),
        2: ProjectDTO(id=2, utility=owner, confidence=1,
                      start_date=date(2027, 1, 1), end_date=date(2027, 12, 31)),
    }
    row = repo.CandidateRow(a_id=1, b_id=2, miles=0)
    monkeypatch.setattr(repo, "candidate_pairs", AsyncMock(return_value=[row]))
    monkeypatch.setattr(repo, "get_projects", AsyncMock(return_value=projects))
    monkeypatch.setattr(repo, "briefs_for_pairs", AsyncMock(return_value={}))
    monkeypatch.setattr(repo, "briefs_for_project", AsyncMock(return_value=[]))
    if entry == "overlaps":
        result = await matching.overlaps(None, 25)
    elif entry == "find_pair":
        result = await matching.find_pair(None, 1, 2, 25)
    elif entry == "pairs_for_project":
        result = await matching.pairs_for_project(None, 1, 25)
    else:
        result = (await matching.rematch_project(None, 1)).pairs
    assert bool(result) == eligible


async def test_rematch_invalidates_brief_for_sister_companies(monkeypatch):
    projects = {
        1: ProjectDTO(id=1, utility="Frp Miller Solar", confidence=1,
                      start_date=date(2027, 1, 1), end_date=date(2027, 12, 31)),
        2: ProjectDTO(id=2, utility="FPL", confidence=1,
                      start_date=date(2027, 1, 1), end_date=date(2027, 12, 31)),
    }
    row = repo.CandidateRow(a_id=1, b_id=2, miles=0)
    brief = repo.StoredBrief(
        pair_id="1-2", a_id=1, b_id=2, text="Old brief", miles=0,
        overlap_days=0, radius=25, stale=False, generated_at=datetime.now(UTC),
    )
    monkeypatch.setattr(repo, "candidate_pairs", AsyncMock(return_value=[row]))
    monkeypatch.setattr(repo, "get_projects", AsyncMock(return_value=projects))
    monkeypatch.setattr(repo, "briefs_for_project", AsyncMock(return_value=[brief]))
    monkeypatch.setattr(repo, "qualifying_brief_pairs", AsyncMock(return_value={"1-2": row}))
    delete = AsyncMock()
    monkeypatch.setattr(repo, "delete_brief", delete)

    result = await matching.rematch_project(None, 1)

    assert result.pairs == []
    assert result.invalidated == ["1-2"]
    delete.assert_awaited_once_with(None, "1-2")
