"""Pure scoring functions for Coordination_Pairs (Req 7). No I/O."""

from __future__ import annotations

import math

from app.models.dto import ScoreFactorsDTO

# Convex-combination weights: non-negative and summing to 1 (Req 7.5). Distance is the
# primary signal and timing a strong secondary one (challenge spec).
WEIGHTS: dict[str, float] = {
    "distance": 0.55,
    "overlap": 0.3,
    "type_similarity": 0.075,
    "voltage_similarity": 0.075,
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


def overlap_score(ratio: float) -> float:
    """The build windows' shared share of their combined span (services/timing.py), 0-1."""
    return _clamp(ratio)


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
    overlap_ratio: float | None,
    type_a: str | None,
    type_b: str | None,
    voltage_a: float | None,
    voltage_b: float | None,
    radius: float,
) -> ScoreFactorsDTO:
    """Compute every factor; missing/invalid inputs zero the factor and flag it (Req 7.6)."""
    indeterminate: list[str] = []
    factors: dict[str, float] = {}

    if _valid_number(miles) and miles >= 0 and _valid_number(radius) and radius >= 0:
        factors["distance"] = distance_score(miles, radius)
    else:
        factors["distance"] = 0.0
        indeterminate.append("distance")

    if _valid_number(overlap_ratio):
        factors["overlap"] = overlap_score(overlap_ratio)
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
