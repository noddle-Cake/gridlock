"""Canonical utility names shared by HIFLD owners and extracted plan projects.

One company shows up as "DUKE ENERGY FLORIDA, LLC" in HIFLD, "DEF" in the FRCC tables and
"Duke Energy Florida" in its own filings. Matching (cross-utility pairs) and map colours
key on the name, so every source goes through `canonical_utility`.
"""

from __future__ import annotations

import re

# Keys are cleaned names (see _key): upper case, no punctuation or corporate suffixes.
ALIASES = {
    "ALABAMA POWER": "Alabama Power",
    "DUKE ENERGY FLORIDA": "Duke Energy Florida",
    "FLORIDA POWER & LIGHT": "Florida Power & Light",
    "FLORIDA POWER AND LIGHT": "Florida Power & Light",
    "GULF POWER": "Florida Power & Light",  # merged into FPL on 2021-01-01
    "FLORIDA PUBLIC UTILITIES": "Florida Public Utilities",
    "GEORGIA POWER": "Georgia Power",
    "GEORGIA TRANSMISSION": "Georgia Transmission Corp",
    "MUNICIPAL ELECTRIC AUTHORITY OF GEORGIA": "MEAG Power",
    "MEAG POWER": "MEAG Power",
    "OGLETHORPE POWER": "Oglethorpe Power",
    "SEMINOLE ELECTRIC COOPERATIVE": "Seminole Electric Cooperative",
    "TALLAHASSEE CITY OF": "City of Tallahassee",
    "CITY OF TALLAHASSEE": "City of Tallahassee",
    "TAMPA ELECTRIC": "Tampa Electric",
    "LAKELAND CITY OF": "City of Lakeland",
    "CITY OF LAKELAND": "City of Lakeland",
    "JEA": "JEA",
    # Abbreviations used as owner columns / prefixes in SERTP and FRCC tables. Only
    # unambiguous ones: "GPC" means Georgia Power in SERTP but Gulf Power in FRCC.
    "DEF": "Duke Energy Florida",
    "FPL": "Florida Power & Light",
    "GAPC": "Georgia Power",
    "GTC": "Georgia Transmission Corp",
    "MEAG": "MEAG Power",
    "SEC": "Seminole Electric Cooperative",
    "TAL": "City of Tallahassee",
    "TEC": "Tampa Electric",
    "LAK": "City of Lakeland",
    # SERTP project-name prefixes (Southern balancing area).
    "SOCO": "Southern Company",  # Georgia/Alabama/Mississippi Power; SERTP doesn't say which
    "PS": "PowerSouth",
    "DU": "Dalton Utilities",
    "POWERSOUTH ENERGY COOPERATIVE": "PowerSouth",
    "SOUTHERN": "Southern Company",  # "Southern Company" minus the stripped suffix
}
_UNKNOWN = {"", "NOT AVAILABLE", "UNKNOWN", "N/A", "NA"}
_SUFFIX = re.compile(r"\b(INC|LLC|L L C|CO|CORP|CORPORATION|COMPANY|THE)\b")
_SMALL_WORDS = {"of", "and", "the", "de"}


def _key(raw: str) -> str:
    text = re.sub(r"[,.]", " ", raw.upper())
    text = _SUFFIX.sub(" ", text)
    return re.sub(r"\s+", " ", text).strip()


def _title(key: str) -> str:
    """'CITY OF OCALA' -> 'City of Ocala'; a lone short word stays an acronym ('TVA')."""
    words = key.split()
    if len(words) == 1 and len(key) <= 4:
        return key
    return " ".join(
        w.lower() if i and w.lower() in _SMALL_WORDS else w.capitalize()
        for i, w in enumerate(words)
    )


def canonical_utility(raw: str | None) -> str | None:
    """Canonical company name; None when there is no usable name."""
    if raw is None or raw.strip().upper() in _UNKNOWN:
        return None
    if "/" in raw:  # jointly owned, e.g. "DEF/SEC"
        parts = [canonical_utility(part) for part in raw.split("/")]
        return " / ".join(p for p in parts if p) or None
    # FRCC also writes joint owners as "DEF-SEC"; split on "-" only when every part is a
    # known abbreviation, so hyphenated names ("Wolverine Power Supply-X") stay whole.
    dashed = [_key(part) for part in raw.split("-")]
    if len(dashed) > 1 and all(d in ALIASES for d in dashed):
        return " / ".join(ALIASES[d] for d in dashed)
    key = _key(raw)
    if not key:
        return None
    return ALIASES.get(key, _title(key))
