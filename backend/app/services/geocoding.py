"""Geocoding_Service: name -> point, county-centroid fallback, retry and ambiguity rules (Req 4)."""

from __future__ import annotations

import asyncio
import csv
import math
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Protocol

import httpx

from app.core.config import get_settings

ATTEMPT_TIMEOUT_S = 10.0
MAX_ATTEMPTS = 3
# Candidates closer than this are the same place (e.g. a town node and its boundary).
DUPLICATE_KM = 3.0

GAZETTEER_PATH = Path(__file__).resolve().parent.parent / "data" / "county_centroids.csv"

STATE_NAMES = {
    "alabama": "AL", "alaska": "AK", "arizona": "AZ", "arkansas": "AR", "california": "CA",
    "colorado": "CO", "connecticut": "CT", "delaware": "DE", "district of columbia": "DC",
    "florida": "FL", "georgia": "GA", "hawaii": "HI", "idaho": "ID", "illinois": "IL",
    "indiana": "IN", "iowa": "IA", "kansas": "KS", "kentucky": "KY", "louisiana": "LA",
    "maine": "ME", "maryland": "MD", "massachusetts": "MA", "michigan": "MI",
    "minnesota": "MN", "mississippi": "MS", "missouri": "MO", "montana": "MT",
    "nebraska": "NE", "nevada": "NV", "new hampshire": "NH", "new jersey": "NJ",
    "new mexico": "NM", "new york": "NY", "north carolina": "NC", "north dakota": "ND",
    "ohio": "OH", "oklahoma": "OK", "oregon": "OR", "pennsylvania": "PA",
    "rhode island": "RI", "south carolina": "SC", "south dakota": "SD", "tennessee": "TN",
    "texas": "TX", "utah": "UT", "vermont": "VT", "virginia": "VA", "washington": "WA",
    "west virginia": "WV", "wisconsin": "WI", "wyoming": "WY", "puerto rico": "PR",
}


@dataclass(frozen=True)
class Candidate:
    lat: float
    lng: float
    label: str = ""


@dataclass(frozen=True)
class GeocodeOutcome:
    lat: float | None = None
    lng: float | None = None
    approximate: bool = False
    requires_review: bool = False

    @property
    def has_geom(self) -> bool:
        return self.lat is not None and self.lng is not None


class Geocoder(Protocol):
    async def resolve(self, name: str) -> list[Candidate]: ...


# ---------------------------------------------------------------- county gazetteer


def _norm(text: str) -> str:
    return re.sub(r"[^a-z0-9 ]", "", text.lower().replace("saint ", "st ").replace("st. ", "st "))


@lru_cache
def _gazetteer() -> dict[tuple[str, str], Candidate]:
    table: dict[tuple[str, str], Candidate] = {}
    with GAZETTEER_PATH.open(encoding="utf-8") as f:
        for row in csv.DictReader(f):
            base = re.sub(
                r"\s+(county|parish|borough|census area|city and borough|municipality)$", "",
                row["name"], flags=re.I,
            )
            cand = Candidate(float(row["lat"]), float(row["lng"]), f"{row['name']}, {row['state']}")
            table[(row["state"], _norm(base))] = cand
    return table


_COUNTY_RE = re.compile(
    r"^\s*(?P<name>.+?)\s+(county|parish|borough|census area)\b[\s,]*(?P<state>[a-z .]+)?\s*$",
    re.I,
)


def _state_code(text: str | None) -> str | None:
    if not text:
        return None
    t = text.strip().rstrip(".").lower()
    if len(t) == 2 and t.isalpha():
        return t.upper()
    return STATE_NAMES.get(t)


def parse_county_ref(
    location_ref: str, state_hint: str | None = None
) -> tuple[str, str | None] | None:
    """'Adams County, PA' -> ('adams', 'PA'); None if the ref isn't county-level."""
    m = _COUNTY_RE.match(location_ref.replace(",", " , ").replace(" , ", ", "))
    if not m:
        return None
    name = m["name"].strip().rstrip(",")
    return _norm(name), _state_code(m["state"]) or _state_code(state_hint)


def county_centroid(location_ref: str, state_hint: str | None = None) -> list[Candidate]:
    parsed = parse_county_ref(location_ref, state_hint)
    if not parsed:
        return []
    name, state = parsed
    table = _gazetteer()
    if state:
        hit = table.get((state, name))
        return [hit] if hit else []
    # No state: every same-named county is a candidate (ambiguous if > 1).
    return [c for (s, n), c in table.items() if n == name]


# ---------------------------------------------------------------- hosted geocoder


def _haversine_km(a: Candidate, b: Candidate) -> float:
    r = 6371.0
    p1, p2 = math.radians(a.lat), math.radians(b.lat)
    dp, dl = p2 - p1, math.radians(b.lng - a.lng)
    h = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(h))


def dedupe_candidates(candidates: list[Candidate], km: float = DUPLICATE_KM) -> list[Candidate]:
    kept: list[Candidate] = []
    for c in candidates:
        if all(_haversine_km(c, k) > km for k in kept):
            kept.append(c)
    return kept


class NominatimGeocoder:
    """OpenStreetMap Nominatim adapter (US only). Respects the 1 req/s usage policy."""

    URL = "https://nominatim.openstreetmap.org/search"
    _lock = asyncio.Lock()

    def __init__(self, user_agent: str) -> None:
        self._headers = {"User-Agent": user_agent}

    async def resolve(self, name: str) -> list[Candidate]:
        async with self._lock:
            async with httpx.AsyncClient(headers=self._headers, timeout=ATTEMPT_TIMEOUT_S) as c:
                resp = await c.get(
                    self.URL,
                    params={"q": name, "format": "jsonv2", "limit": 5, "countrycodes": "us"},
                )
            await asyncio.sleep(1.0)
        resp.raise_for_status()
        results = [
            Candidate(float(r["lat"]), float(r["lon"]), r.get("display_name", ""))
            for r in resp.json()
        ]
        return dedupe_candidates(results)


class NullGeocoder:
    async def resolve(self, name: str) -> list[Candidate]:
        return []


def default_geocoder() -> Geocoder:
    settings = get_settings()
    if settings.geocoder == "nominatim":
        return NominatimGeocoder(settings.geocoder_user_agent)
    return NullGeocoder()


# ---------------------------------------------------------------- service


class GeocodingService:
    def __init__(self, geocoder: Geocoder, *, attempt_timeout: float = ATTEMPT_TIMEOUT_S) -> None:
        self._geocoder = geocoder
        self._timeout = attempt_timeout

    async def resolve_with_retry(self, query: str) -> GeocodeOutcome:
        """Up to MAX_ATTEMPTS, each bounded by the timeout (Req 4.3-4.5).

        An attempt fails when it raises or times out, and is retried. A completed attempt
        is final: exactly one candidate resolves; zero or several leave geom unset and
        mark the project for review.
        """
        for _ in range(MAX_ATTEMPTS):
            try:
                candidates = await asyncio.wait_for(
                    self._geocoder.resolve(query), timeout=self._timeout
                )
            except Exception:  # timeout, network, HTTP error: a failed attempt
                continue
            if len(candidates) == 1:
                c = candidates[0]
                return GeocodeOutcome(lat=c.lat, lng=c.lng)
            return GeocodeOutcome(requires_review=True)
        return GeocodeOutcome(requires_review=True)

    async def geocode(
        self, location_ref: str, *, kind: str = "", state: str | None = None
    ) -> GeocodeOutcome:
        ref = (location_ref or "").strip()
        if not ref:
            return GeocodeOutcome(requires_review=True)

        # County-level reference -> county centroid, marked approximate (Req 4.2).
        if kind == "county" or parse_county_ref(ref, state):
            hits = county_centroid(ref, state)
            if len(hits) == 1:
                return GeocodeOutcome(lat=hits[0].lat, lng=hits[0].lng, approximate=True)
            if len(hits) > 1:
                return GeocodeOutcome(requires_review=True)
            outcome = await self.resolve_with_retry(ref)
            if outcome.has_geom:
                return GeocodeOutcome(lat=outcome.lat, lng=outcome.lng, approximate=True)
            return outcome

        # Substation / town name -> point (Req 4.1).
        query = ref
        if state and not re.search(rf"\b{re.escape(state)}\b", ref, re.I):
            query = f"{ref}, {state}"
        outcome = await self.resolve_with_retry(query)
        if outcome.has_geom:
            return outcome

        # Substations are usually named for their town and rarely mapped by name;
        # fall back to the town, flagged approximate.
        town = re.sub(r"\s+(?=,)", "", _SUBSTATION_WORDS.sub("", query))
        town = re.sub(r"\s{2,}", " ", town).strip(" ,")
        if town and town.lower() != query.lower():
            fallback = await self.resolve_with_retry(town)
            if fallback.has_geom:
                return GeocodeOutcome(lat=fallback.lat, lng=fallback.lng, approximate=True)
        return outcome


_SUBSTATION_WORDS = re.compile(
    r"\b(substation|sub|switching station|switchyard|station)\b\.?", re.I
)
