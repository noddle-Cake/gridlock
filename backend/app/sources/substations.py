"""Offline substation gazetteer: plan substation names -> public OSM coordinates.

Reads `app/data/osm_substations.csv`, built once by `scripts/build_substation_cache.py`
from OpenStreetMap (already public). Names in transmission plans ("LAWSONS FORK TIE",
"WINDER PRIMARY", "ENTERPRISE TS") rarely match OSM spelling exactly, so both sides are
reduced to a key with the equipment words stripped before comparing.
"""

from __future__ import annotations

import csv
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from app.services.geocoding import Candidate, dedupe_candidates

CACHE_PATH = Path(__file__).resolve().parent.parent / "data" / "osm_substations.csv"

# Words that describe the equipment, not the place.
_EQUIPMENT = re.compile(
    r"\b(substations?|subs?|switching|switch|stations?|switchyard|yard|tie|primary|"
    r"distribution|transmission|ts|ss|dist|plant|steam|generating|power|energy|center|"
    r"electric|facility|hydro|dam|cc|ct|sw|sta|kv|tap|junction|jct)\b"
)
_ABBREV = {"mt": "mount", "mtn": "mountain", "ft": "fort", "st": "saint", "hwy": "highway",
           "rd": "road", "n": "north", "s": "south", "e": "east", "w": "west"}


def name_key(name: str) -> str:
    """'Lawsons Fork Tie' / 'LAWSON'S FORK SUBSTATION' -> 'lawsons fork'."""
    text = name.lower().replace("&", " and ").replace("’", "").replace("'", "")
    text = re.sub(r"\(.*?\)", " ", text)            # "(Yates to Clem)"
    text = re.sub(r"\d+(\.\d+)?(\s*/\s*\d+(\.\d+)?)*\s*kv\b", " ", text)  # "230/100/44 kV"
    text = re.sub(r"#\s*\d+|\bno\.?\s*\d+\b", " ", text)  # "#2", "No. 2"
    text = re.sub(r"[^a-z0-9 ]", " ", text)
    words = [_ABBREV.get(w, w) for w in text.split()]
    text = _EQUIPMENT.sub(" ", " ".join(words))
    return re.sub(r"\s+", " ", text).strip()


@dataclass(frozen=True)
class Substation:
    state: str
    name: str
    power: str
    operator: str
    lat: float
    lng: float


@lru_cache
def _index() -> dict[str, list[Substation]]:
    table: dict[str, list[Substation]] = {}
    if not CACHE_PATH.exists():
        return table
    with CACHE_PATH.open(encoding="utf-8") as f:
        for row in csv.DictReader(f):
            key = name_key(row["name"])
            if not key:
                continue
            table.setdefault(key, []).append(Substation(
                row["state"], row["name"], row["power"], row["operator"],
                float(row["lat"]), float(row["lng"]),
            ))
    return table


def candidates(
    name: str, states: list[str], *, operator_hint: str | None = None
) -> list[Substation]:
    """Distinct OSM substations this plan name could refer to (empty if none).

    Several same-named features within ~3 km are one place (a substation node and its
    fence polygon). An operator match narrows the list; substations win over power
    plants of the same name.
    """
    key = name_key(name)
    if len(key) < 3:
        return []
    hits = [s for s in _index().get(key, []) if s.state in states]
    if not hits:
        return []
    subs = [s for s in hits if s.power == "substation"] or hits
    if operator_hint:
        words = {w for w in re.findall(r"[a-z]{3,}", operator_hint.lower())} - {"energy", "power"}
        owned = [s for s in subs if words & set(re.findall(r"[a-z]{3,}", s.operator.lower()))]
        subs = owned or subs
    places = dedupe_candidates([Candidate(s.lat, s.lng, s.name) for s in subs])
    return [next(s for s in subs if (s.lat, s.lng) == (p.lat, p.lng)) for p in places]


def lookup(
    name: str, states: list[str], *, operator_hint: str | None = None
) -> Substation | None:
    """The one OSM substation this plan name refers to, or None if absent/ambiguous."""
    found = candidates(name, states, operator_hint=operator_hint)
    return found[0] if len(found) == 1 else None
