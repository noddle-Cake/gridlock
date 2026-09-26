"""The region GridMerge plans for: the Southeast around the Sperry challenge pair (Dominion
Energy South Carolina, Georgia Power) plus Florida. Loaders keep only projects here.
"""

from __future__ import annotations

import csv
import math
from functools import lru_cache

from app.services.geocoding import GAZETTEER_PATH

REGION_STATES: tuple[str, ...] = ("SC", "GA", "FL")
# A point farther than this from every county centre is offshore or outside the US.
_MAX_KM = 90.0


@lru_cache
def _centroids() -> list[tuple[str, float, float]]:
    with GAZETTEER_PATH.open(encoding="utf-8") as f:
        return [(r["state"], float(r["lat"]), float(r["lng"])) for r in csv.DictReader(f)]


def _km(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lng2 - lng1)
    h = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 6371.0 * 2 * math.asin(math.sqrt(h))


def state_at(lat: float, lng: float) -> str | None:
    """The state of the nearest county centre: good away from borders, approximate within a
    county's width of one. None when nothing is near (offshore)."""
    state, dist = min(((s, _km(lat, lng, clat, clng)) for s, clat, clng in _centroids()),
                      key=lambda t: t[1])
    return state if dist <= _MAX_KM else None


def in_region(lat: float | None, lng: float | None, owner_states: list[str] | None = None) -> bool:
    """A located project inside the region, or an unplaced one whose owner operates only in
    region states (e.g. Georgia Transmission Corp)."""
    if lat is not None and lng is not None:
        return state_at(lat, lng) in REGION_STATES
    return bool(owner_states) and set(owner_states) <= set(REGION_STATES)
