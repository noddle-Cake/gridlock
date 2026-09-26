"""Rough coordination value (Sperry bonus)."""

from app.db import repository as repo
from app.models.dto import ProjectDTO
from app.services import impact, matching
from tests.conftest import requires_db, run_db


def proj(pid: int, kv: int = 115, cost: int | None = None) -> ProjectDTO:
    return ProjectDTO(id=pid, utility=f"U{pid}", confidence=1, voltage_kv=kv, cost_usd=cost)


def labels(est) -> list[str]:
    return [i.label for i in est.items]


def test_nearer_tiers_add_sharing():
    a, b = proj(1), proj(2)
    crews = impact.estimate(tier=3, a=a, b=b, shared_km=None, windows_overlap=True)
    site = impact.estimate(tier=2, a=a, b=b, shared_km=None, windows_overlap=True)
    land = impact.estimate(tier=1, a=a, b=b, shared_km=2.0, windows_overlap=True)
    touch = impact.estimate(tier=0, a=a, b=b, shared_km=2.0, windows_overlap=True)
    assert len(labels(crews)) < len(labels(site)) < len(labels(land)) < len(labels(touch))
    assert "Share right-of-way land" in labels(land)
    assert crews.total_low < site.total_low < land.total_low < touch.total_low
    assert impact.estimate(tier=4, a=a, b=b, shared_km=None, windows_overlap=True) is None


def test_timing_items_only_count_when_windows_overlap():
    est = impact.estimate(tier=2, a=proj(1), b=proj(2), shared_km=None, windows_overlap=False)
    assert est.total_low == 0 and est.total_high == 0
    assert est.if_aligned_low > 0 and not est.windows_overlap


def test_published_cost_scales_mobilization():
    est = impact.estimate(tier=3, a=proj(1, cost=20_000_000), b=proj(2), shared_km=None,
                          windows_overlap=True)
    (item,) = est.items
    assert (item.low, item.high) == (200_000, 600_000)
    assert "$20,000,000" in item.basis


def test_shared_land_uses_narrower_row():
    est = impact.estimate(tier=1, a=proj(1, kv=230), b=proj(2, kv=115), shared_km=10.0,
                          windows_overlap=True)
    land = next(i for i in est.items if i.acres)
    # 10 km x half of 30 m (115 kV) = 150,000 m2 ~ 37.1 acres
    assert land.acres == 37.1 and est.acres == 37.1


@requires_db
def test_shared_corridor_length_between_parallel_lines():
    # Two east-west lines ~0.55 km apart, overlapping along ~28 km of longitude.
    a = repo.NewProject(utility="A", confidence=1, lat=33.0, lng=-81.75,
                        route=[(33.0, -82.0), (33.0, -81.5)])
    b = repo.NewProject(utility="B", confidence=1, lat=33.005, lng=-81.55,
                        route=[(33.005, -81.8), (33.005, -81.3)])
    c = repo.NewProject(utility="C", confidence=1, lat=33.0, lng=-81.4)  # a point

    async def body(conn):
        await repo.insert_projects(conn, [a, b, c])
        return {(r.a_id, r.b_id): r for r in
                await repo.candidate_pairs(conn, 40 / matching.KM_PER_MILE)}

    rows = run_db(body)
    assert 28 < rows[(1, 2)].shared_km < 31
    assert rows[(1, 3)].shared_km is None
