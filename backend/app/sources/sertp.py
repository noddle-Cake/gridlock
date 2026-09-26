"""SERTP preliminary 10-year expansion plan (Non-CEII) -> project records.

The report is one project sheet per balancing authority area, every entry laid out as

    In-Service 2027
    Year:
    Project Name: GTC: ADAMSVILLE - BUZZARD ROOST 230 KV REBUILD
    Description: Rebuild about 5 miles of the ... line with ...
    Supporting The Adamsville - Buzzard Roost 230kV line overloads under contingency.
    Statement:

which pdfplumber reads cleanly, so this is a deterministic parser (no LLM call). The page
header interleaves a watermark with the area name; the area is recovered from the 18 pt
header characters alone.

SERTP: listed projects "do not represent a commitment to build". Every record keeps the
PDF page it came from.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from app.services.owners import canonical_utility

SOURCE_URL = (
    "https://www.southeasternrtp.com/docs/general/2026/"
    "2026_SERTP_Preliminary_Expansion_Plan_Report_(Non-CEII).pdf"
)

# Balancing authority area -> (default owner, states the area covers).
AREAS: dict[str, tuple[str, list[str]]] = {
    "AECI": ("Associated Electric Cooperative", ["MO", "AR", "OK"]),
    "DUKE CAROLINAS": ("Duke Energy Carolinas", ["NC", "SC"]),
    "DUKE PROGRESS EAST": ("Duke Energy Progress", ["NC", "SC"]),
    "DUKE PROGRESS WEST": ("Duke Energy Progress", ["NC"]),
    "LG&E/KU": ("LG&E and KU", ["KY", "VA"]),
    "SOUTHERN": ("Southern Company", ["GA", "AL", "MS", "FL"]),
    "TVA": ("TVA", ["TN", "AL", "MS", "KY", "GA", "NC", "VA"]),
}
# Southern-area owners that sit in fewer states than the whole area.
OWNER_STATES = {
    "Georgia Transmission Corp": ["GA"],
    "MEAG Power": ["GA"],
    "Dalton Utilities": ["GA"],
    "PowerSouth": ["AL", "FL"],
}

_FIELDS = re.compile(
    r"In-Service\s+(?P<year>\d{4})\s*\n\s*Year:\s*\n"
    r"Project Name:\s*(?P<name>.*?)\n"
    r"Description:\s*(?P<desc>.*?)\n"
    r"Supporting\s*(?P<support>.*?)(?=\nIn-Service\s+\d{4}\s*\n|\Z)",
    re.S,
)
_FOOTER = re.compile(r"\n?\d{2}/\d{2}/\d{4}\s+Page\s+\d+\s+of\s+\d+\s*$")
_KV = re.compile(r"(\d{2,3}(?:\.\d+)?)\s*(?:/\s*\d{2,3}\s*)?KV", re.I)
_PREFIX = re.compile(r"^([A-Z&]{2,6}):\s*")

_LINE_WORDS = re.compile(
    r"\b(TRANSMISSION LINES?|LINES?|TL|RECONDUCTOR|REBUILD|LOOP[- ]IN|FIBER|CIRCUIT)\b"
)
_SUB_WORDS = re.compile(
    r"\b(SUBSTATION|SUB|SWITCHING STATION|AUTOTRANSFORMERS?|TRANSFORMERS?|BREAKERS?|"
    r"STATCOM|CAPACITORS?|REACTORS?|CONDENSER|BUS|SVC|TS|SS)\b"
)
# Everything after the place names in a project title.
_TAIL = re.compile(
    r"\s+(\d{2,3}(\.\d+)?\s*(/\s*\d{2,3}\s*)?KV\b.*|NEW\b.*|TRANSMISSION\b.*|TL\b.*|"
    r"LINE\b.*|SUBSTATION\b.*|SUB\b.*|AREA\b.*|NETWORK\b.*|PROTECTION\b.*|"
    r"RELAY\b.*|BREAKER\b.*|STATCOM\b.*|SWITCHING\b.*|MODERNIZATION\b.*|"
    r"GENERATION\b.*|SOLAR\b.*|IMPROVEMENTS?\b.*|UPGRADES?\b.*|REBUILD\b.*|"
    r"RECONDUCTOR\b.*|REACTOR\b.*|CAP\b.*|BANK\b.*|AUTOBANK\b.*)$"
)
_VERB = re.compile(r"^(REPLACE|INSTALL|ADD|CONSTRUCT|UPGRADE|EXPAND|REMOVE .* AT)\s+")


@dataclass
class SertpEntry:
    page: int
    area: str
    year: int
    name: str
    description: str
    supporting: str
    owner: str = ""
    states: list[str] = field(default_factory=list)

    @property
    def title(self) -> str:
        """Project name without the owner prefix(es)."""
        text = self.name
        while m := _PREFIX.match(text):
            text = text[m.end():]
        return text.strip()

    @property
    def voltage_kv(self) -> float | None:
        found = [float(v) for v in _KV.findall(self.name)] or [
            float(v) for v in _KV.findall(self.description)
        ]
        return max(found) if found else None

    @property
    def endpoints(self) -> list[str]:
        """Place names in the title: 'A - B 230 KV ...' -> ['A', 'B']."""
        head = self.title.upper().split(",")[0]
        head = _VERB.sub("", _TAIL.sub("", head)).strip(" -–")
        parts = re.split(r"\s+[-–]\s+|\s+TO\s+|\s*&\s*", head)
        return [p.strip() for p in parts if len(p.strip()) >= 3]

    @property
    def kind(self) -> str:
        title = self.title.upper()
        if _SUB_WORDS.search(title) and not _LINE_WORDS.search(title):
            return "substation"
        if len(self.endpoints) >= 2 or _LINE_WORDS.search(title):
            return "transmission line"
        return "substation"

    def excerpt(self) -> str:
        return (
            f"In-Service Year: {self.year}\nProject Name: {self.name}\n"
            f"Description: {self.description}\nSupporting Statement: {self.supporting}"
        )


def _clean(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def _area(page) -> str:
    """Area name from the 18 pt header, e.g. 'SOUTHERN Balancing Authority Area...'."""
    chars = sorted(
        (c for c in page.chars if c["top"] < 80 and round(c["size"]) == 18),
        key=lambda c: (round(c["top"]), c["x0"]),
    )
    text = "".join(c["text"] for c in chars)
    return text.split(" Balancing Authority")[0].strip()


def _owner(entry: SertpEntry) -> tuple[str, list[str]]:
    default_owner, states = AREAS.get(entry.area, (entry.area.title(), []))
    m = _PREFIX.match(entry.name)
    if entry.area == "SOUTHERN" and m:
        owner = canonical_utility(m.group(1)) or default_owner
        return owner, OWNER_STATES.get(owner, states)
    return default_owner, states


def parse_page_text(body: str, *, page: int, area: str) -> list[SertpEntry]:
    body = _FOOTER.sub("", body.strip())
    entries = []
    for m in _FIELDS.finditer(body):
        name = _clean(m["name"])
        desc = m["desc"]
        support = re.sub(r"^\s*Statement:\s*|\n\s*Statement:\s*", " ", m["support"])
        # "Project Name" can wrap; the wrapped words land before "Description:".
        entry = SertpEntry(
            page=page, area=area, year=int(m["year"]), name=name,
            description=_clean(desc), supporting=_clean(support),
        )
        entry.owner, entry.states = _owner(entry)
        entries.append(entry)
    return entries


def parse_report(path: Path, *, areas: set[str] | None = None) -> list[SertpEntry]:
    import pdfplumber

    entries: list[SertpEntry] = []
    with pdfplumber.open(path) as pdf:
        for page_no, page in enumerate(pdf.pages, start=1):
            area = _area(page)
            if areas and area not in areas:
                continue
            body = page.crop((0, 80, page.width, page.height)).extract_text() or ""
            entries += parse_page_text(body, page=page_no, area=area)
    return entries
