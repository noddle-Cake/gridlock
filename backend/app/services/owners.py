"""Canonical utility names shared by HIFLD owners and extracted plan projects.

One company shows up as "DUKE ENERGY FLORIDA, LLC" in HIFLD, "DEF" in the FRCC tables and
"Duke Energy Florida" in its own filings. Matching (cross-utility pairs) and map colours
key on the name, so every source goes through `canonical_utility`.
"""

from __future__ import annotations

import csv
import re
from functools import lru_cache
from pathlib import Path

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
    "FRP": "Florida Renewable Partners",
    "DESC": "Dominion Energy South Carolina",
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
    "PEC": "PowerSouth",  # FRCC Form 13: PowerSouth Energy Cooperative (Panhandle lines)
    "DU": "Dalton Utilities",
    "POWERSOUTH ENERGY COOPERATIVE": "PowerSouth",
    "SOUTHERN": "Southern Company",  # "Southern Company" minus the stripped suffix
    # Other SERTP balancing areas, as named in SERTP headers and EIA-860M entity names.
    "TVA": "TVA",
    "TENNESSEE VALLEY AUTHORITY": "TVA",
    "DUKE ENERGY CAROLINAS": "Duke Energy Carolinas",
    "DUKE ENERGY PROGRESS": "Duke Energy Progress",
    "DUKE ENERGY PROGRESS - (NC)": "Duke Energy Progress",
    "DUKE ENERGY PROGRESS - (SC)": "Duke Energy Progress",
    "LOUISVILLE GAS & ELECTRIC": "LG&E and KU",
    "KENTUCKY UTILITIES": "LG&E and KU",
    "LG&E AND KU": "LG&E and KU",
    "ASSOCIATED ELECTRIC COOPERATIVE": "Associated Electric Cooperative",
}
# Operating companies that plan as one entity. SERTP lists Southern's Georgia, Alabama and
# Mississippi projects as "Southern Company" while Georgia Power's own IRP lists the same
# projects as "Georgia Power"; without this, one project would pair with its own copy as a
# 0 km "cross-utility" overlap.
PLANNING_ENTITY = {
    "Southern Company": "Southern Company",
    "Georgia Power": "Southern Company",
    "Alabama Power": "Southern Company",
    "Mississippi Power": "Southern Company",
}

# Corporate ownership is broader than a shared transmission planning entity. Keep
# this separate from PLANNING_ENTITY, which also scopes substation geocoding overrides.
# Sources and the matching policy are documented in source_docs/company_ownership.md.
# Keys use canonical_utility's capitalization, including "Nextera" from EIA names.
CORPORATE_PARENT = {
    **PLANNING_ENTITY,
    "Southern Power": "Southern Company",
    "Florida Power & Light": "NextEra Energy",
    "Florida Renewable Partners": "NextEra Energy",
    "Florida Renewable Partners Holdings": "NextEra Energy",
    "Nextera Energy": "NextEra Energy",
    "Nextera Energy Resources": "NextEra Energy",
    "Nextera Energy Resources - Ercot": "NextEra Energy",
    "Nextera Energy Capital Holdings": "NextEra Energy",
    "Duke Energy": "Duke Energy",
    "Duke Energy Carolinas": "Duke Energy",
    "Duke Energy Progress": "Duke Energy",
    "Duke Energy Florida": "Duke Energy",
    "Duke Energy Ohio": "Duke Energy",
    "Duke Energy Indiana": "Duke Energy",
    "Dominion Energy": "Dominion Energy",
    "Dominion Energy South Carolina": "Dominion Energy",
    "Scana": "Dominion Energy",
}

# FRP solar project LLCs appear as individual EIA utilities. Restrict the rule to
# solar entities rather than treating every business starting with "FRP" as NextEra.
_FRP_SOLAR = re.compile(r"FRP .+ SOLAR(?: [IVX\d]+)?$")

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


def planning_entity(utility: str) -> str:
    """The entity a utility plans with; pairs within one entity aren't cross-utility."""
    name = utility.strip()
    return PLANNING_ENTITY.get(name, name).lower()


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


@lru_cache(maxsize=1)
def ownership_registry() -> dict[str, dict[str, str]]:
    path = Path(__file__).resolve().parents[1] / "data" / "company_ownership.csv"
    with path.open(encoding="utf-8", newline="") as f:
        return {canonical_utility(row["utility"]): row for row in csv.DictReader(f)}


def _parent(owner: str) -> str | None:
    row = ownership_registry().get(owner)
    if row is not None:
        return row["corporate_group"] if row["status"] == "verified" else None
    if _FRP_SOLAR.fullmatch(_key(owner)):
        return "NextEra Energy"
    return CORPORATE_PARENT.get(owner)


@lru_cache(maxsize=4096)
def ownership_review_required(utility: str) -> bool:
    name = canonical_utility(utility)
    return name is None or any(_parent(owner) is None for owner in name.split(" / "))


@lru_cache(maxsize=4096)
def corporate_entities(utility: str) -> frozenset[str]:
    """Known parents, retaining individual identities for unreviewed names.

    Identity alone does not establish independent ownership: different_companies
    also requires every owner to have a reviewed corporate family.
    """
    name = canonical_utility(utility)
    if name is None:
        return frozenset()
    return frozenset((_parent(owner) or owner).casefold() for owner in name.split(" / "))


def _withheld(utility: str) -> bool:
    """An owner the ownership audit looked at and couldn't place (status `review`)."""
    name = canonical_utility(utility)
    return name is not None and any(
        (row := ownership_registry().get(owner)) is not None and row["status"] != "verified"
        for owner in name.split(" / "))


# Words that name a phase or technology of one development, not its developer:
# "Atlas Solar IV" / "Atlas BESS IV", "Lazy U Solar 1" / "Lazy U ESS 2".
_FAMILY_NOISE = {
    "solar", "pv", "photovoltaic", "bess", "ess", "storage", "battery", "energy", "wind",
    "hybrid", "project", "projects", "farm", "park", "center", "facility", "plant", "station",
    "generating", "power", "phase", "llc", "lp", "inc", "co", "company", "the", "and", "of",
    "one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten",
}
# Leading words shared by unrelated developments, so not a developer's name on their own.
_GENERIC_LEAD = {
    "big", "little", "north", "south", "east", "west", "new", "old", "upper", "lower", "lake",
    "river", "creek", "valley", "mountain", "hill", "prairie", "mesa", "rock", "green", "blue",
    "red", "white", "black", "sun", "sunny", "grand", "high", "pine", "oak", "cedar", "city",
    "county", "town", "st", "saint", "fort", "mount", "twin", "long", "clear", "sand", "silver",
}
_ROMAN = re.compile(r"^(?=[ivx]+$)x{0,3}(ix|iv|v?i{0,3})$")


def _family_stem(utility: str) -> tuple[str, ...]:
    words = re.findall(r"[a-z]+|\d+", utility.casefold())
    return tuple(w for w in words
                 if not w.isdigit() and w not in _FAMILY_NOISE and not _ROMAN.match(w))


def same_project_family(utility_a: str, utility_b: str) -> bool:
    """Names that read as one developer's projects, so likely one owner, once phase,
    technology and numbering words are dropped: one a leading part of the other
    ("Bridgewater Solar" / "Bridgewater Solar 2"), or the same distinctive first word, as
    developers prefix their project companies ("Evergy Kansas Central" / "Evergy Missouri
    West", "Cve Us Pa Dayton 404" / "Cve Us Pa Kittanning 406"). Names with nothing left to
    compare ("Solar 1" / "Solar 2") count as one family too."""
    a, b = _family_stem(utility_a), _family_stem(utility_b)
    short, long_ = sorted((a, b), key=len)
    if not short or long_[: len(short)] == short:
        return True
    return a[0] == b[0] and a[0] not in _GENERIC_LEAD


def different_companies(utility_a: str, utility_b: str) -> bool:
    """Whether two projects' companies may be flagged as a cross-company match.

    Never for missing names, a common known owner (including a joint owner), or an owner
    the audit withheld pending evidence (status `review`). Companies with a verified
    corporate family match on those grounds alone. Companies not in the registry yet
    (most of EIA's nationwide project companies) match unless their names read as one
    development's phases (`same_project_family`); such pairs carry
    `ownership_review_required` on the unverified project so the UI can say so.
    """
    a, b = corporate_entities(utility_a), corporate_entities(utility_b)
    if not (a and b and a.isdisjoint(b)) or _withheld(utility_a) or _withheld(utility_b):
        return False
    if not (ownership_review_required(utility_a) or ownership_review_required(utility_b)):
        return True
    return not same_project_family(canonical_utility(utility_a) or "",
                                   canonical_utility(utility_b) or "")
