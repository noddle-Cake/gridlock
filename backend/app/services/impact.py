"""Rough coordination value of a flagged pair (Sperry bonus: a cost/impact estimate).

Each distance tier unlocks one more kind of sharing, and nearer tiers keep everything the
farther ones allow:

    under 40 km  -> one crew/equipment mobilization instead of two
    under 8 km   -> one laydown yard and shared deliveries
    under 1.6 km -> shared right-of-way land, access roads and permits
    touching     -> one coordinated outage and crossing design

Sharing crews, yards and outages only happens if the two build windows overlap; when they
don't, those items are reported as "if schedules were aligned" and left out of the total.

Every figure below is a planning ASSUMPTION for a first-pass conversation, not a quote or a
sourced benchmark. They are ranges on purpose; change them here.
"""

from __future__ import annotations

from app.models.dto import ImpactDTO, ImpactItemDTO, ProjectDTO

ACRE_M2 = 4046.86

# Typical right-of-way width (m) by voltage class: (max kV, width). Assumption.
ROW_WIDTH_M = [(69, 23.0), (138, 30.0), (230, 38.0), (345, 46.0), (10_000, 61.0)]
DEFAULT_ROW_WIDTH_M = 30.0
# A second line in a shared corridor still widens it; assume half the narrower ROW is saved.
ROW_SHARE = 0.5
LAND_USD_PER_ACRE = (5_000, 20_000)  # easement cost, rural Southeast. Assumption.

# Avoided mobilization: share of the smaller project's published cost, or a flat range when
# neither filing publishes a cost (Georgia Power's IRP redacts them). Assumptions.
MOBILIZATION_PCT = (0.01, 0.03)
MOBILIZATION_FLAT_USD = (150_000, 400_000)
LAYDOWN_YARD_USD = (100_000, 300_000)
PERMITS_ACCESS_USD = (50_000, 200_000)
OUTAGE_COORDINATION_USD = (50_000, 250_000)

ASSUMPTIONS = [
    "Ranges are planning assumptions for a first conversation, not quotes.",
    "Right-of-way widths: 23 m ≤69 kV, 30 m ≤138 kV, 38 m ≤230 kV, 46 m ≤345 kV, 61 m above;"
    " a shared corridor saves half the narrower width; easements $5k–$20k per acre.",
    "One mobilization avoided: 1–3% of the smaller published project cost, or $150k–$400k"
    " when costs are not published.",
    "Laydown yard $100k–$300k; access roads and permits $50k–$200k; coordinated outage and"
    " crossing design $50k–$250k.",
    "Crew, yard and outage sharing count only when the build windows overlap.",
]


def row_width_m(kv: float | None) -> float:
    if not kv:
        return DEFAULT_ROW_WIDTH_M
    return next(w for top, w in ROW_WIDTH_M if kv <= top)


def _scale(r: tuple[float, float], k: float) -> tuple[int, int]:
    return round(r[0] * k), round(r[1] * k)


def estimate(
    *, tier: int | None, a: ProjectDTO, b: ProjectDTO, shared_km: float | None,
    windows_overlap: bool,
) -> ImpactDTO | None:
    """None when the pair is outside every tier (40 km or more)."""
    if tier is None or tier > 3:
        return None
    items: list[ImpactItemDTO] = []

    costs = [c for c in (a.cost_usd, b.cost_usd) if c]
    if costs:
        low, high = _scale(MOBILIZATION_PCT, min(costs))
        basis = f"1–3% of the smaller published project cost (${min(costs):,})"
    else:
        low, high = MOBILIZATION_FLAT_USD
        basis = "flat range; neither filing publishes a cost"
    items.append(ImpactItemDTO(label="Share crews & equipment (one mobilization)",
                               low=low, high=high, basis=basis, needs_timing=True))

    if tier <= 2:
        items.append(ImpactItemDTO(label="Share a laydown yard and deliveries",
                                   low=LAYDOWN_YARD_USD[0], high=LAYDOWN_YARD_USD[1],
                                   basis="one yard instead of two", needs_timing=True))
    if tier <= 1:
        items.append(ImpactItemDTO(label="Share access roads and permitting",
                                   low=PERMITS_ACCESS_USD[0], high=PERMITS_ACCESS_USD[1],
                                   basis="one access plan and permit package"))
        if shared_km:
            width = min(row_width_m(a.voltage_kv), row_width_m(b.voltage_kv))
            acres = shared_km * 1000 * width * ROW_SHARE / ACRE_M2
            low, high = _scale(LAND_USD_PER_ACRE, acres)
            items.append(ImpactItemDTO(
                label="Share right-of-way land", low=low, high=high, acres=round(acres, 1),
                basis=f"{shared_km:.1f} km of shared corridor × half of a {width:.0f} m ROW",
            ))
    if tier == 0:
        items.append(ImpactItemDTO(label="Coordinate one outage and the crossing design",
                                   low=OUTAGE_COORDINATION_USD[0],
                                   high=OUTAGE_COORDINATION_USD[1],
                                   basis="one outage window and one crossing design",
                                   needs_timing=True))

    counted = [i for i in items if windows_overlap or not i.needs_timing]
    return ImpactDTO(
        items=items,
        total_low=sum(i.low for i in counted), total_high=sum(i.high for i in counted),
        if_aligned_low=sum(i.low for i in items), if_aligned_high=sum(i.high for i in items),
        windows_overlap=windows_overlap,
        acres=sum(i.acres or 0 for i in items) or None,
        assumptions=ASSUMPTIONS,
    )
