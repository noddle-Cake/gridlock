"""Ranking follows Sperry's distance tiers first, then the composite score."""

from app.models.dto import CoordinationPairDTO, ProjectDTO, ScoreFactorsDTO
from app.services.matching import KM_PER_MILE, distance_band, rank_key, tier


def pair(km: float, composite: float) -> CoordinationPairDTO:
    miles = km / KM_PER_MILE
    band = distance_band(miles)
    a = ProjectDTO(id=1, utility="A", confidence=1)
    b = ProjectDTO(id=2, utility="B", confidence=1)
    return CoordinationPairDTO(
        id=f"{km}-{composite}", project_a=a, project_b=b, miles=miles, band=band,
        tier=tier(band), overlap_days=0,
        scores=ScoreFactorsDTO(distance=0, overlap=0, type_similarity=0, voltage_similarity=0,
                               composite=composite),
    )


def test_tiers_match_the_challenge():
    assert [tier(distance_band(km / KM_PER_MILE)) for km in (0, 1.0, 5, 20, 39)] == [
        0, 1, 2, 3, 3]
    assert tier(distance_band(41 / KM_PER_MILE)) == 4


def test_closer_tier_beats_higher_score():
    right_of_way = pair(1.2, composite=0.30)
    logistics = pair(6.0, composite=0.95)
    crews_near = pair(12.0, composite=0.60)
    crews_far = pair(30.0, composite=0.80)  # same tier as crews_near: score decides
    ranked = sorted([crews_near, logistics, crews_far, right_of_way], key=rank_key)
    assert ranked == [right_of_way, logistics, crews_far, crews_near]
