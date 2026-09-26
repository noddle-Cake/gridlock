"""Place a plan entry that names substations, not coordinates.

1. Each named substation is looked up in the offline OSM gazetteer (substations.py).
2. A name OSM doesn't know as a substation is searched once as a place (Nominatim, limited
   to the Southeast) and resolved to its county; the county centre is used and the
   project is marked approximate.
3. Anything still unresolved or ambiguous gets no point and is marked for review.

Place lookups are cached in `app/data/place_cache.json` (committed), so a re-run makes no
network calls. Only public data is used: OSM features and Census county centroids.
"""

from __future__ import annotations

import json
import math
import time
from dataclasses import dataclass
from pathlib import Path

import httpx

from app.services.geocoding import STATE_NAMES, county_centroid
from app.sources.substations import lookup

PLACE_CACHE = Path(__file__).resolve().parent.parent / "data" / "place_cache.json"
NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
SOUTHEAST_VIEWBOX = "-100.0,40.8,-75.0,24.0"  # left,top,right,bottom
PLACE_TYPES = {
    "city", "town", "village", "hamlet", "locality", "suburb", "neighbourhood",
    "isolated_dwelling", "county", "administrative", "census",
}
# Two endpoints of one planned line/project further apart than this aren't trusted as
# a pair; the first resolved endpoint is used instead of the midpoint.
MAX_SPAN_MILES = 150.0


def _miles(a: tuple[float, float], b: tuple[float, float]) -> float:
    p1, p2 = math.radians(a[0]), math.radians(b[0])
    dp, dl = p2 - p1, math.radians(b[1] - a[1])
    h = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 3958.8 * 2 * math.asin(math.sqrt(h))


@dataclass
class Located:
    lat: float | None = None
    lng: float | None = None
    approximate: bool = False
    requires_review: bool = False
    how: str = ""  # human-readable trail, appended to the excerpt


class PlaceCache:
    """Name -> list of {state, county, lat, lng} Southeast place matches (Nominatim)."""

    def __init__(self, path: Path = PLACE_CACHE, *, offline: bool = False,
                 user_agent: str = "GridMerge/0.1 (hackathon demo)") -> None:
        self._path = path
        self._offline = offline
        self._ua = user_agent
        self._data: dict[str, list[dict]] = (
            json.loads(path.read_text()) if path.exists() else {}
        )
        self._dirty = False

    def places(self, name: str) -> list[dict]:
        key = name.strip().upper()
        if key in self._data or self._offline:
            return self._data.get(key, [])
        resp = None
        for _ in range(3):
            try:
                resp = httpx.get(
                    NOMINATIM_URL,
                    params={"q": name, "format": "jsonv2", "limit": 10, "countrycodes": "us",
                            "addressdetails": 1, "viewbox": SOUTHEAST_VIEWBOX, "bounded": 1},
                    headers={"User-Agent": self._ua}, timeout=15,
                )
                time.sleep(1.1)  # Nominatim usage policy: 1 request/second
                if resp.status_code == 200:
                    break
            except httpx.HTTPError:
                time.sleep(2)
        if resp is None or resp.status_code != 200:
            return []  # not cached; retried next run
        found = []
        for r in resp.json():
            if r.get("type") not in PLACE_TYPES and r.get("addresstype") not in PLACE_TYPES:
                continue
            addr = r.get("address", {})
            state = STATE_NAMES.get((addr.get("state") or "").lower())
            if not state:
                continue
            found.append({
                "state": state, "county": addr.get("county", ""),
                "lat": round(float(r["lat"]), 3), "lng": round(float(r["lon"]), 3),
                "label": r.get("display_name", "")[:120],
            })
        self._data[key] = found
        self._dirty = True
        return found

    def save(self) -> None:
        if self._dirty:
            self._path.write_text(json.dumps(self._data, indent=1, sort_keys=True) + "\n")
            self._dirty = False


def _county_point(place: dict) -> tuple[float, float, str] | None:
    """County centre for a place match; the place itself if it has no county (VA cities)."""
    county = place.get("county") or ""
    if county:
        hits = county_centroid(county if "county" in county.lower() or "parish" in
                               county.lower() else f"{county} County", place["state"])
        if len(hits) == 1:
            return hits[0].lat, hits[0].lng, f"{county}, {place['state']} (county centre)"
    return place["lat"], place["lng"], f"{place['label']} (place)"


def locate(
    endpoints: list[str], states: list[str], places: PlaceCache, *, operator: str | None = None
) -> Located:
    exact: list[tuple[float, float, str]] = []
    rough_names: list[str] = []
    for name in endpoints:
        sub = lookup(name, states, operator_hint=operator)
        if sub:
            exact.append((sub.lat, sub.lng, f"{name} = OSM {sub.power} '{sub.name}' ({sub.state})"))
        else:
            rough_names.append(name)

    rough: list[tuple[float, float, str]] = []
    for name in rough_names:
        matches = [p for p in places.places(name) if p["state"] in states]
        points = {}
        for p in matches:
            pt = _county_point(p)
            if pt:
                points[(round(pt[0], 2), round(pt[1], 2))] = pt
        anchor = exact[0] if exact else None
        if len(points) == 1:
            pt = next(iter(points.values()))
            rough.append((pt[0], pt[1], f"{name} ~ {pt[2]}"))
        elif points and anchor:
            # Same-named towns in several states: take the one nearest the resolved end.
            pt = min(points.values(), key=lambda q: _miles(q[:2], anchor[:2]))
            if _miles(pt[:2], anchor[:2]) <= MAX_SPAN_MILES:
                rough.append((pt[0], pt[1], f"{name} ~ {pt[2]} (nearest of {len(points)})"))

    resolved = exact + rough
    if not resolved:
        return Located(requires_review=True, how="No substation or place match; needs review.")
    first = resolved[0]
    if len(resolved) >= 2 and _miles(resolved[0][:2], resolved[1][:2]) <= MAX_SPAN_MILES:
        a, b = resolved[0], resolved[1]
        lat, lng = (a[0] + b[0]) / 2, (a[1] + b[1]) / 2
        used = [a, b]
    else:
        lat, lng = first[0], first[1]
        used = [first]
    approximate = bool(rough) or len(used) < len(endpoints)
    how = "Located: " + "; ".join(u[2] for u in used)
    if len(used) == 2:
        how += " (midpoint)"
    return Located(round(lat, 3), round(lng, 3), approximate=approximate, how=how)
