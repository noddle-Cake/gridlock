"""Pure scoring functions for Coordination_Pairs (Req 7). No I/O."""

from __future__ import annotations

import math

from app.models.dto import ScoreFactorsDTO

# Convex-combination weights: non-negative and summing to 1 (Req 7.5).
WEIGHTS: dict[str, float] = {
    "distance": 0.4,
    "overlap": 0.3,
    "type_similarity": 0.15,
    "voltage_similarity": 0.15,
}
# Voltage difference (kV) at which voltage-similarity reaches 0.
V_SCALE = 500.0


def _clamp(x: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, x))


def _valid_number(x: object) -> bool:
    return isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x)


def distance_score(miles: float, radius: float) -> float:
    """1.0 at 0 miles, decreasing linearly to 0.0 at/beyond `radius` (Req 7.1)."""
    if radius <= 0:
        return 1.0 if miles <= 0 else 0.0
    return _clamp(1.0 - miles / radius)


def overlap_score(overlap_days: float, max_overlap: float) -> float:
    """0.0 when overlap <= 0, rising linearly to 1.0 at/beyond `max_overlap` (Req 7.2)."""
    if overlap_days <= 0:
        return 0.0
    if max_overlap <= 0:
        return 1.0
    return _clamp(overlap_days / max_overlap)


def type_similarity(type_a: str, type_b: str) -> float:
    """1.0 when equal, 0.0 otherwise (Req 7.3)."""
    return 1.0 if type_a == type_b else 0.0


def voltage_similarity(v_a: float, v_b: float) -> float:
    """1.0 when equal, decreasing linearly in |v_a - v_b| (Req 7.4)."""
    return _clamp(1.0 - abs(v_a - v_b) / V_SCALE)


def composite_score(factors: dict[str, float]) -> float:
    """Weighted convex combination of the four factors (Req 7.5)."""
    return _clamp(sum(WEIGHTS[name] * factors[name] for name in WEIGHTS))


def score_pair(
    *,
    miles: float | None,
    overlap_days: float | None,
    type_a: str | None,
    type_b: str | None,
    voltage_a: float | None,
    voltage_b: float | None,
    radius: float,
    max_overlap: float,
) -> ScoreFactorsDTO:
    """Compute every factor; missing/invalid inputs zero the factor and flag it (Req 7.6)."""
    indeterminate: list[str] = []
    factors: dict[str, float] = {}

    if _valid_number(miles) and miles >= 0 and _valid_number(radius) and radius >= 0:
        factors["distance"] = distance_score(miles, radius)
    else:
        factors["distance"] = 0.0
        indeterminate.append("distance")

    if _valid_number(overlap_days) and _valid_number(max_overlap):
        factors["overlap"] = overlap_score(overlap_days, max_overlap)
    else:
        factors["overlap"] = 0.0
        indeterminate.append("overlap")

    if type_a and type_b:
        factors["type_similarity"] = type_similarity(str(type_a), str(type_b))
    else:
        factors["type_similarity"] = 0.0
        indeterminate.append("type_similarity")

    if _valid_number(voltage_a) and _valid_number(voltage_b) and voltage_a > 0 and voltage_b > 0:
        factors["voltage_similarity"] = voltage_similarity(voltage_a, voltage_b)
    else:
        factors["voltage_similarity"] = 0.0
        indeterminate.append("voltage_similarity")

    return ScoreFactorsDTO(
        **factors,
        composite=composite_score(factors),
        indeterminate_factors=indeterminate,
    )
