"""Search bar: one box for ZIP codes, states, companies, and project text.

The parser is deterministic and cheap, so the client can call GET /search as the planner
types. It never calls the LLM: natural-language questions go to POST /ask
(services/ask.py), whose tools run the same `ProjectFilter` queries.

    "33157"                 -> projects within 25 miles of the ZIP (its OSM point)
    "Florida" / "FL"        -> state
    "FPL"                   -> company, by acronym ("Florida Power & Light")
    "Florida Power & Light" -> company (a full name beats the state it contains)
    "FPL 33101"             -> company + ZIP
    "Georgia transmission"  -> state + project type
"""

from __future__ import annotations

import asyncio
import csv
import difflib
import math
import re
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

import asyncpg
import httpx

from app.core.config import get_settings
from app.db import repository as repo
from app.models.dto import (
    CompanySuggestionDTO,
    LocationSuggestionDTO,
    SearchHitDTO,
    SearchInterpretationDTO,
    SearchResponse,
)
from app.models.enums import ProjectType
from app.services.geocoding import STATE_NAMES, Candidate, NominatimGeocoder, _gazetteer

ZIP_PATH = Path(__file__).resolve().parent.parent / "data" / "zip_centroids.csv"
ZIP_OSM_PATH = ZIP_PATH.with_name("zip_osm_points.csv")
# An OSM point farther than this from the Census one is a different place, not a better
# centre for the same ZIP.
ZIP_MAX_SHIFT_MILES = 50.0
ZIP_LOOKUP_TIMEOUT_S = 3.0
MAX_QUERY_CHARS = 200
MAX_WINDOW = 6  # longest company name, in words, tried as one phrase
ZIP_WIDER_RADII = (50.0, 100.0)  # tried in turn when nothing is near a ZIP

STATE_CODES = set(STATE_NAMES.values())
STATE_LABELS = {
    code: " ".join(w if w == "of" else w.capitalize() for w in name.split())
    for name, code in STATE_NAMES.items()
}
# Two-letter codes that are also everyday words: only a state when typed in capitals
# ("OR") or alone ("or" as the whole query is still Oregon).
AMBIGUOUS_CODES = {"in", "or", "me", "hi", "ok", "oh", "de", "la", "ma", "al", "co", "id", "mo",
                   "ne", "wa", "pa"}

TYPE_WORDS = {
    "transmission": ProjectType.TRANSMISSION_LINE, "line": ProjectType.TRANSMISSION_LINE,
    "lines": ProjectType.TRANSMISSION_LINE, "substation": ProjectType.SUBSTATION,
    "substations": ProjectType.SUBSTATION, "generation": ProjectType.GENERATION,
    "generator": ProjectType.GENERATION, "generators": ProjectType.GENERATION,
    "plant": ProjectType.GENERATION, "plants": ProjectType.GENERATION,
}

STOPWORDS = {
    "a", "an", "the", "in", "on", "at", "of", "for", "and", "or", "near", "around", "by",
    "with", "to", "from", "within", "projects", "project", "show", "me", "list", "find",
    "all", "any", "what", "which", "who", "where", "when", "how", "many", "much", "are",
    "is", "do", "does", "there", "have", "has", "utility", "utilities", "company",
    "companies", "zip", "code", "state", "miles", "mile", "planned",
}

# Words dropped from company names before comparing: "Georgia Transmission Corp" is
# found by "Georgia Transmission".
NAME_FILLER = {"and", "of", "the"}
NAME_SUFFIXES = {"inc", "incorporated", "llc", "corp", "corporation", "co", "company", "ltd",
                 "lp", "llp"}

_QUESTION_START = re.compile(
    r"^(what|which|who|whose|where|when|why|how|is|are|was|were|do|does|did|can|could|"
    r"should|would|will|list|show|tell|compare|summari[sz]e|explain|give)\b",
    re.I,
)
_TOKEN = re.compile(r"[\w&'.-]+")
_ZIP = re.compile(r"^(\d{5})(-\d{4})?$")


def looks_like_question(q: str) -> bool:
    """Reads as a question for the AI rather than a lookup ("Which utilities ...?")."""
    q = q.strip()
    return q.endswith("?") or (len(q.split()) >= 3 and bool(_QUESTION_START.match(q)))


def _words(text: str) -> list[str]:
    return re.findall(r"[a-z0-9]+", text.lower().replace("&", " and "))


def _core(words: list[str]) -> list[str]:
    """Name words without filler and trailing corporate suffixes."""
    out = [w for w in words if w not in NAME_FILLER]
    while len(out) > 1 and out[-1] in NAME_SUFFIXES:
        out.pop()
    return out


# ---------------------------------------------------------------- company index


@dataclass
class CompanyIndex:
    """Every utility in the dataset, keyed for exact, acronym, and prefix lookups."""

    counts: dict[str, int]
    by_key: dict[str, list[str]] = field(default_factory=dict)
    by_acronym: dict[str, list[str]] = field(default_factory=dict)
    core: dict[str, list[str]] = field(default_factory=dict)

    @classmethod
    def build(cls, counts: dict[str, int]) -> CompanyIndex:
        index = cls(counts=counts)
        for name in counts:
            words = _words(name)
            core = _core(words)
            if not core:
                continue
            index.core[name] = core
            index.by_key.setdefault(" ".join(core), []).append(name)
            content = [w for w in words if w not in NAME_FILLER]
            acronyms = {"".join(w[0] for w in core), "".join(w[0] for w in content)}
            # A name that starts with its own acronym: "TVA", "MEAG Power".
            first = name.split()[0]
            if first.isupper() and first.isalpha():
                acronyms.add(first.lower())
            for a in acronyms:
                if len(a) >= 3:
                    index.by_acronym.setdefault(a, []).append(name)
        return index

    def exact(self, phrase_words: list[str]) -> list[str]:
        core = _core(phrase_words)
        hits = self.by_key.get(" ".join(core), []) if core else []
        if not hits and len(phrase_words) == 1:
            hits = self.by_acronym.get(phrase_words[0], [])
        return hits

    def prefix(self, phrase_words: list[str]) -> list[str]:
        """Companies whose name starts with these words; the last word may be partial
        ("florida pow" while typing)."""
        want = [w for w in phrase_words if w not in NAME_FILLER]
        if not want:
            return []
        hits = []
        for name, core in self.core.items():
            if len(core) < len(want):
                continue
            head, last = want[:-1], want[-1]
            if core[: len(head)] == head and core[len(head)].startswith(last):
                hits.append(name)
        return hits

    def resolve(self, name: str) -> list[str]:
        """Companies a typed name refers to: full name, acronym, or name prefix."""
        words = _words(name)
        return (self.exact(words) or self.prefix(words)) if words else []

    def suggest(
        self, text: str, matched: list[str], limit: int, *, typos: bool = True
    ) -> list[str]:
        """Companies for the dropdown: parsed matches first, then names starting with, or
        with words starting with, what was typed."""
        want = _words(text)
        scored: dict[str, int] = {name: 3 for name in matched}
        key = " ".join(want)
        if len(key) >= 3:
            for name, core in self.core.items():
                if name in scored:
                    continue
                full = " ".join(_words(name))
                if full.startswith(key) or " ".join(core).startswith(key):
                    scored[name] = 2
                elif all(any(w.startswith(q) for w in core) for q in want if q not in STOPWORDS):
                    if any(q not in STOPWORDS for q in want):
                        scored[name] = 1
        if typos and not scored and len(key) >= 4:
            # A typo ("florda powr"): compare with each name cut to as many words.
            n = len(want)
            heads = {" ".join(core[:n]): name for name, core in self.core.items()}
            for head in difflib.get_close_matches(key, list(heads), n=limit, cutoff=0.75):
                scored[heads[head]] = 0
        ranked = sorted(scored, key=lambda n: (-scored[n], -self.counts.get(n, 0), n))
        return ranked[:limit]


# ---------------------------------------------------------------- ZIP gazetteer


@lru_cache
def _zip_table() -> dict[str, tuple[float, float]]:
    with ZIP_PATH.open(encoding="utf-8") as f:
        return {row["zip"]: (float(row["lat"]), float(row["lng"])) for row in csv.DictReader(f)}


def zip_centroid(zip_code: str) -> tuple[float, float] | None:
    """Census ZCTA internal point for a five-digit ZIP, if it is a real ZCTA."""
    return _zip_table().get(zip_code)


@lru_cache
def _zip_osm_table() -> dict[str, tuple[float, float]]:
    """OSM points looked up ahead of time (scripts/build_zip_cache.py)."""
    if not ZIP_OSM_PATH.exists():
        return {}
    with ZIP_OSM_PATH.open(encoding="utf-8") as f:
        return {row["zip"]: (float(row["lat"]), float(row["lng"])) for row in csv.DictReader(f)}


_zip_osm_live: dict[str, tuple[float, float] | None] = {}


async def fetch_osm_zip(zip_code: str) -> tuple[float, float] | None:
    """Nominatim's point for a US postcode: the middle of the OSM addresses that carry it.

    Shares the geocoder's lock and holds it for a second after the request (the usage
    policy's 1 req/s) without making this search wait out that second.
    """
    lock = NominatimGeocoder._lock
    await lock.acquire()
    try:
        headers = {"User-Agent": get_settings().geocoder_user_agent}
        async with httpx.AsyncClient(headers=headers, timeout=ZIP_LOOKUP_TIMEOUT_S) as c:
            resp = await c.get(NominatimGeocoder.URL, params={
                "postalcode": zip_code, "country": "us", "format": "jsonv2", "limit": 1,
            })
    finally:
        asyncio.get_running_loop().call_later(1.0, lock.release)
    resp.raise_for_status()
    hits = [r for r in resp.json() if r.get("addresstype") == "postcode"]
    return (float(hits[0]["lat"]), float(hits[0]["lon"])) if hits else None


def _miles_apart(a: tuple[float, float], b: tuple[float, float]) -> float:
    k = math.cos(math.radians((a[0] + b[0]) / 2))
    return 69.0 * math.hypot(a[0] - b[0], (a[1] - b[1]) * k)


async def locate_zip(zip_code: str) -> tuple[float, float] | None:
    """Where a five-digit ZIP is on the map, or None if it isn't a real ZCTA.

    A Census ZCTA internal point only has to fall inside the ZIP's polygon, which for a big
    rural ZIP can be nowhere near anyone: 33034's is in the Everglades, 18 miles west of
    Florida City. OpenStreetMap puts the ZIP where its addresses are, so its point wins
    when it has one (committed table, else a live Nominatim lookup, remembered per process).
    The Census table still decides which ZIPs are real, and is the fallback.
    """
    census = zip_centroid(zip_code)
    if census is None:
        return None
    osm = _zip_osm_table().get(zip_code)
    if osm is None and get_settings().geocoder == "nominatim":
        if zip_code not in _zip_osm_live:
            try:
                _zip_osm_live[zip_code] = await fetch_osm_zip(zip_code)
            except (httpx.HTTPError, ValueError, KeyError):
                return census  # not remembered: a later search tries again
        osm = _zip_osm_live[zip_code]
    if osm and _miles_apart(osm, census) <= ZIP_MAX_SHIFT_MILES:
        return osm
    return census


def nearest_county(lat: float, lng: float) -> Candidate | None:
    best, best_d = None, math.inf
    k = math.cos(math.radians(lat))
    for c in _gazetteer().values():
        d = (c.lat - lat) ** 2 + ((c.lng - lng) * k) ** 2
        if d < best_d:
            best, best_d = c, d
    return best


# ---------------------------------------------------------------- parsing


@dataclass
class ParsedQuery:
    raw: str
    zip: str | None = None
    states: list[str] = field(default_factory=list)
    utilities: list[str] = field(default_factory=list)
    types: list[ProjectType] = field(default_factory=list)
    terms: list[str] = field(default_factory=list)
    is_question: bool = False


def state_code(text: str) -> str | None:
    """'Georgia', 'GA', or 'ga' -> 'GA'."""
    t = text.strip()
    return STATE_NAMES.get(t.lower()) or (t.upper() if t.upper() in STATE_CODES else None)


def _state_code(token: str, *, whole_query: bool) -> str | None:
    low = token.lower()
    if low in STATE_NAMES:
        return STATE_NAMES[low]
    if len(token) == 2 and token.upper() in STATE_CODES:
        if token.isupper() or whole_query or low not in AMBIGUOUS_CODES:
            return token.upper()
    return None


def parse_query(q: str, companies: CompanyIndex) -> ParsedQuery:
    raw = q.strip()[:MAX_QUERY_CHARS]
    parsed = ParsedQuery(raw=raw, is_question=looks_like_question(raw))
    # "FPL's" -> "FPL"
    tokens = [re.sub(r"'s$", "", t.strip(".'-"), flags=re.I) for t in _TOKEN.findall(raw)]
    tokens = [t for t in tokens if t]
    used = [False] * len(tokens)

    # ZIP code (ZIP+4 is accepted and trimmed).
    for i, t in enumerate(tokens):
        m = _ZIP.match(t)
        if m and parsed.zip is None:
            parsed.zip = m.group(1)
            used[i] = True

    def windows(max_n: int):
        for n in range(min(max_n, len(tokens)), 0, -1):
            for i in range(len(tokens) - n + 1):
                if not any(used[i : i + n]):
                    yield i, n

    def plain(words: list[str]) -> bool:
        """Only state names, type words, and stopwords: not a company name."""
        text = " ".join(words)
        return text in STATE_NAMES or all(
            w in STOPWORDS or w in TYPE_WORDS or w in STATE_NAMES or w in NAME_FILLER
            for w in words
        )

    # Companies first, longest phrase first, so "Florida Power & Light" is one company
    # rather than the state of Florida plus two loose words.
    for i, n in windows(MAX_WINDOW):
        if any(used[i : i + n]):
            continue
        words = _words(" ".join(tokens[i : i + n]))
        if not words:
            continue
        if plain(words):
            # "Georgia transmission" is a state and a type, even though Georgia
            # Transmission Corp exists; the dropdown still offers that company.
            continue
        hits = companies.exact(words) or (companies.prefix(words) if n >= 2 else [])
        if hits:
            parsed.utilities.extend(h for h in hits if h not in parsed.utilities)
            used[i : i + n] = [True] * n

    # States: full names (up to three words, "District of Columbia") or codes.
    for i, n in windows(3):
        if any(used[i : i + n]):
            continue
        phrase = " ".join(tokens[i : i + n])
        code = (
            STATE_NAMES.get(phrase.lower()) if n > 1
            else _state_code(phrase, whole_query=len(tokens) == 1)
        )
        if code:
            if code not in parsed.states:
                parsed.states.append(code)
            used[i : i + n] = [True] * n

    for i, t in enumerate(tokens):
        if used[i]:
            continue
        low = t.lower()
        if low in TYPE_WORDS:
            if TYPE_WORDS[low] not in parsed.types:
                parsed.types.append(TYPE_WORDS[low])
        elif low not in STOPWORDS and (len(low) >= 2 or low.isdigit()):
            parsed.terms.append(low)
    return parsed


def _ahead():
    """Search, like the map and Review, lists only work not yet finished (PLANNING_FROM)."""
    return get_settings().planning_cutoff


async def to_filter(
    parsed: ParsedQuery,
) -> tuple[repo.ProjectFilter, tuple[float, float] | None]:
    """The project filter for a parsed query, and the ZIP point it searched around."""
    radius = get_settings().search_zip_radius_miles
    f = repo.ProjectFilter(
        utilities=list(parsed.utilities), states=list(parsed.states),
        types=[t.value for t in parsed.types], terms=list(parsed.terms), radius_miles=radius,
        ahead_of=_ahead(),
    )
    point = await locate_zip(parsed.zip) if parsed.zip else None
    if point:
        f.near = point
    elif parsed.zip:
        f.terms.append(parsed.zip)  # not a ZCTA: fall back to the text
    return f, point


async def search_with_fallback(
    conn: asyncpg.Connection, f: repo.ProjectFilter, *, limit: int
) -> tuple[repo.ProjectSearch, bool]:
    """Search `f`, loosening it until something matches: a ZIP search widens its radius
    (25 -> 50 -> 100 miles, updating `f.radius_miles`), and free text with letters is
    retried as a trigram near-match so a typo ("Florda Powr") still finds something.
    Returns (result, fuzzy)."""
    result = await repo.search_projects(conn, f, limit=limit)
    if f.near:
        for radius in ZIP_WIDER_RADII:
            if result.total or radius <= f.radius_miles:
                continue
            f.radius_miles = radius
            result = await repo.search_projects(conn, f, limit=limit)
    words = [t for t in f.terms if re.search(r"[a-z]", t)]
    if result.total or not words:
        return result, False
    fuzzy = repo.ProjectFilter(
        utilities=f.utilities, states=f.states, types=f.types, near=f.near,
        radius_miles=f.radius_miles, fuzzy_text=" ".join(words), ahead_of=f.ahead_of,
    )
    fuzzy_result = await repo.search_projects(conn, fuzzy, limit=limit)
    return (fuzzy_result, True) if fuzzy_result.total else (result, False)


async def load_companies(conn: asyncpg.Connection) -> CompanyIndex:
    return CompanyIndex.build(await repo.utility_counts(conn))


# ---------------------------------------------------------------- GET /search


def _state_suggestions(parsed: ParsedQuery) -> list[str]:
    """Parsed states, else states whose name starts with what was typed ("geor")."""
    if parsed.states:
        return parsed.states
    text = parsed.raw.lower().strip()
    if len(text) < 3 or parsed.utilities or parsed.zip:
        return []
    return [code for name, code in STATE_NAMES.items() if name.startswith(text)][:3]


async def run_search(conn: asyncpg.Connection, q: str, *, limit: int) -> SearchResponse:
    companies = await load_companies(conn)
    parsed = parse_query(q, companies)
    f, point = await to_filter(parsed)
    interpretation = SearchInterpretationDTO(
        zip=parsed.zip, zip_found=point is not None, states=parsed.states,
        utilities=parsed.utilities, types=parsed.types, terms=parsed.terms,
    )
    locations: list[LocationSuggestionDTO] = []
    if point:
        county = nearest_county(*point)
        interpretation.zip_label = f"ZIP {parsed.zip}" + (
            f" · near {county.label}" if county else ""
        )
        # Everything near the ZIP, whatever else was typed, widening like the search.
        near = repo.ProjectFilter(near=point, radius_miles=f.radius_miles, ahead_of=f.ahead_of)
        n = await repo.count_projects(conn, near)
        for radius in ZIP_WIDER_RADII:
            if not n and radius > near.radius_miles:
                near.radius_miles = radius
                n = await repo.count_projects(conn, near)
        locations.append(LocationSuggestionDTO(
            kind="zip", code=parsed.zip, project_count=n,
            label=f"{interpretation.zip_label} · {near.radius_miles:g} mi",
        ))
    for code in _state_suggestions(parsed):
        n = await repo.count_projects(conn, repo.ProjectFilter(states=[code], ahead_of=f.ahead_of))
        locations.append(LocationSuggestionDTO(
            kind="state", code=code, label=STATE_LABELS.get(code, code), project_count=n,
        ))

    # Typo matching only when nothing else in the query was recognised.
    typos = not (parsed.states or parsed.zip or parsed.types)
    company_names = companies.suggest(parsed.raw, parsed.utilities, limit=5, typos=typos)
    suggestions = [
        CompanySuggestionDTO(utility=name, project_count=companies.counts.get(name, 0))
        for name in company_names
    ]

    if f.empty:
        return SearchResponse(
            query=parsed.raw, interpretation=interpretation, companies=suggestions,
            locations=locations, projects=[], project_ids=[], total=0,
            suggest_ai=parsed.is_question,
        )
    result, fuzzy = await search_with_fallback(conn, f, limit=limit)
    interpretation.fuzzy = fuzzy
    bounds = list(result.bounds) if result.bounds else None
    if point:
        interpretation.radius_miles = f.radius_miles
        # Keep the ZIP at the centre even if every match is farther north (or in
        # any one direction). Fitting the ZIP and matches together would instead
        # send the planner halfway towards the projects. Empty ZIPs still locate.
        lat, lng = point
        lat_span = max(abs(bounds[0] - lat), abs(bounds[2] - lat)) if bounds else 0
        lng_span = max(abs(bounds[1] - lng), abs(bounds[3] - lng)) if bounds else 0
        bounds = [lat - lat_span, lng - lng_span, lat + lat_span, lng + lng_span]
    return SearchResponse(
        query=parsed.raw,
        interpretation=interpretation,
        companies=suggestions,
        locations=locations,
        projects=[
            SearchHitDTO(**p.model_dump(), miles=round(result.miles[p.id], 1)
                         if p.id in result.miles else None)
            for p in result.projects
        ],
        project_ids=result.ids,
        total=result.total,
        bounds=bounds,
        suggest_ai=parsed.is_question,
    )
