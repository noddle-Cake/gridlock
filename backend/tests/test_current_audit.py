"""Regression cases from the September 2026 source and corporate ownership audit."""

from datetime import date

import pytest

from app.db import repository as repo
from app.models.dto import ProjectDTO
from app.models.enums import DatePrecision
from app.services import matching
from app.services.owners import canonical_utility, ownership_registry, ownership_review_required
from app.services.project_status import OPERATING_EVIDENCE
from app.sources import desc, snapshot
from tests.conftest import requires_db, run_db


def test_every_snapshot_company_has_an_explicit_ownership_decision():
    owners = {canonical_utility(p.utility) for s in snapshot.SOURCES
              for p in snapshot.read_export(snapshot.EXTRACTED_DIR / s.export)}
    assert owners <= ownership_registry().keys()
    assert ownership_review_required("Unresearched Solar LLC")
    assert not ownership_review_required("DEF/SEC")


@pytest.mark.parametrize("text,month", [("04/31/26", 4), ("06/31/2026", 6)])
def test_invalid_source_day_keeps_only_month_precision(text, month):
    entry = desc.DescEntry(1, "Test", "1", "", "", "In Progress", text)
    assert entry.in_service == (date(2026, month, 1),) * 2
    assert entry.date_precision == DatePrecision.MONTH
    assert "invalid calendar day" in entry.excerpt()


def test_new_desc_snapshot_dates_and_citations():
    rows = snapshot.read_export(snapshot.EXTRACTED_DIR / snapshot.DESC.export)
    assert len(rows) == 54
    assert all(p.source_url == desc.SOURCE_URL for p in rows)
    assert all(p.raw_excerpt and p.source_page for p in rows)
    assert rows[0].end_precision == DatePrecision.MONTH
    jasper = next(p for p in rows if "Jasper" in p.name and "#2" in p.name)
    assert jasper.end_date == date(2026, 12, 1)


def test_match_requires_thirty_remaining_days_not_historical_overlap():
    projects = {i: ProjectDTO(id=i, utility=u, confidence=1,
                              start_date=date(2026, 1, 1), end_date=date(2026, 10, 1))
                for i, u in [(1, "JEA"), (2, "FPL")]}
    pair = matching._build_pair(repo.CandidateRow(1, 2, 1), projects, 25)
    assert pair.overlap_days > 30
    assert matching.qualifies(pair, matching.Rules(date(2026, 9, 2), 30))
    assert not matching.qualifies(pair, matching.Rules(date(2026, 9, 3), 30))


@requires_db
def test_operating_evidence_excludes_current_lists_search_and_matches():
    evidence = OPERATING_EVIDENCE[0]

    async def body(conn):
        await repo.insert_projects(conn, [
            repo.NewProject(utility="Kingstree West 115", name=evidence.name,
                            source_url=evidence.plan_url, confidence=1, lat=33, lng=-80,
                            start_date=date(2026, 10, 1), end_date=date(2026, 10, 1),
                            start_precision=DatePrecision.MONTH, end_precision=DatePrecision.MONTH),
            repo.NewProject(utility="JEA", name="Independent project", confidence=1,
                            lat=33, lng=-80, end_date=date(2027, 1, 1)),
        ])
        projects = await repo.list_projects(conn)
        plant = next(p for p in projects if p.name == evidence.name)
        assert not matching.is_past(plant, date(2026, 9, 22))
        assert matching.is_past(plant, evidence.as_of)
        assert plant.end_date == date(2026, 10, 1)  # planned source preserved
        assert plant.operating_source_url == evidence.source_url
        current = await repo.search_projects(
            conn, repo.ProjectFilter(ahead_of=evidence.as_of), limit=10)
        assert current.total == 1 and current.projects[0].utility == "JEA"
        archive = await repo.search_projects(conn, repo.ProjectFilter(), limit=10)
        assert archive.total == 2
        assert not await matching.overlaps(conn, 25, rules=matching.Rules(evidence.as_of, 30))

    run_db(body)


@requires_db
def test_new_desc_retires_only_old_loader_and_rolls_back_on_failure(monkeypatch):
    async def body(conn):
        old = snapshot.DESC_LEGACY
        rows = snapshot.read_export(snapshot.EXTRACTED_DIR / old.export)[:1]
        old_id = await snapshot.save(conn, old, rows)
        upload = await repo.insert_plan(conn, utility="DESC", source_url=old.source_url,
                                        filename=old.filename, detected_format="pdf")
        original = snapshot.replace_source

        async def fail(*args, **kwargs):
            raise RuntimeError("insertion failed")

        monkeypatch.setattr(snapshot, "replace_source", fail)
        with pytest.raises(RuntimeError):
            await snapshot.save(conn, snapshot.DESC, rows)
        assert await conn.fetchval("SELECT count(*) FROM plans WHERE id=$1::uuid", old_id) == 1
        monkeypatch.setattr(snapshot, "replace_source", original)
        await snapshot.save(conn, snapshot.DESC, rows)
        assert await conn.fetchval("SELECT count(*) FROM plans WHERE id=$1::uuid", old_id) == 0
        assert await conn.fetchval(
            "SELECT count(*) FROM plans WHERE id=$1::uuid", upload.plan_id) == 1

    run_db(body)


@requires_db
def test_refreshed_desc_has_future_georgia_power_matches():
    async def body(conn):
        for source in [snapshot.DESC, snapshot.GPC_ITS]:
            rows = snapshot.read_export(snapshot.EXTRACTED_DIR / source.export)
            await snapshot.save(conn, source, rows)
        pairs = await matching.overlaps(conn, 40 / matching.KM_PER_MILE,
                                       rules=matching.Rules(date(2026, 9, 27), 30))
        return [p for p in pairs if {p.project_a.utility, p.project_b.utility} ==
                {"Dominion Energy South Carolina", "Georgia Power"}]

    pairs = run_db(body)
    assert len(pairs) == 8
    assert any("Jasper" in (p.project_a.name + p.project_b.name) and
               "goshen" in (p.project_a.name + p.project_b.name).lower() and
               p.miles * matching.KM_PER_MILE < 5 for p in pairs)
