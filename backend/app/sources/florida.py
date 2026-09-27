"""Florida utilities' planned transmission lines, read deterministically (no LLM).

1. FRCC 2026 Load and Resource Plan, Form 13 "Summary and Specifications of Proposed
   Transmission Lines" (as of January 1, 2026): every FRCC utility's proposed lines on
   page 62 (Duke Energy Florida, FPL, Tampa Electric, Lakeland, Seminole) and the non-FRCC
   ones on page 85 (PowerSouth, "PEC"). Rows look like

       DEF  NOVA SUBSTATION  SWEETWATER SUBSTATION  1.0  01/2028  230  919  NA

   The two terminals are separate columns, so a row's terminal words are split at the
   widest gap between words, which works for both pages' layouts.
2. City of Tallahassee 2026 Ten Year Site Plan, Table 4.2 "Planned Transmission Projects"
   (page 49): its own 115 kV reconductoring, not in Form 13.
"""

from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from app.services.owners import canonical_utility

FRCC_URL = ("https://www.floridapsc.com/pscfiles/website-files/PDF/Utilities/Electricgas/"
            "TenYearSitePlans/2026/FRCC_RLRP.pdf")
FRCC_PAGES = (62, 85)  # 1-based PDF pages holding Form 13
TALLAHASSEE_URL = ("https://www.floridapsc.com/pscfiles/website-files/PDF/Utilities/"
                   "Electricgas/TenYearSitePlans/2026/City%20of%20Tallahassee.pdf")
TALLAHASSEE_PAGE = 49
TALLAHASSEE = "City of Tallahassee"

STATES = ["FL"]
BOUNDS = (24.3, 31.1, -87.7, -79.8)  # Florida (min lat, max lat, min lng, max lng)

_OWNER = re.compile(r"^[A-Z]{2,4}(?:-[A-Z]{2,4})?$")
_NUMBER = re.compile(r"^\d+(?:\.\d+)?$")
_TAIL = re.compile(
    r"^(?P<month>\d{1,2})\s*/\s*(?P<year>\d{4})\s+(?P<kv>\d+(?:\.\d+)?)\s+(?P<mva>\d+)"
)
# Words naming the equipment rather than the place, dropped from project names.
_EQUIPMENT = re.compile(r"\s+(SUBSTATION|SWITCHING STATION)$")


@dataclass
class LineEntry:
    page: int
    source_url: str
    owner_code: str  # as printed: "DEF", "DEF-SEC", "PEC"
    terminal_a: str
    terminal_b: str
    miles: float | None
    in_service: date  # first of the month; the filings give month and year
    voltage_kv: float
    note: str = ""  # anything the parser corrected, quoted in the excerpt
    row_text: str = ""

    @property
    def owner(self) -> str:
        return canonical_utility(self.owner_code) or self.owner_code

    @property
    def endpoints(self) -> list[str]:
        """Terminal names to locate: 'DEF MARTIN WEST' -> 'MARTIN WEST' (the owner code
        prefixes a terminal when the owners differ), 'JD PAGE (TEC)' -> 'JD PAGE'."""
        codes = set(self.owner_code.split("-"))
        out = []
        for t in (self.terminal_a, self.terminal_b):
            words = t.split()
            if len(words) > 1 and words[0] in codes:
                words = words[1:]
            out.append(re.sub(r"\s*\(.*?\)", "", " ".join(words)).strip())
        return out

    @property
    def title(self) -> str:
        a, b = (_EQUIPMENT.sub("", n).title() for n in self.endpoints)
        return f"{a} - {b} {self.voltage_kv:g} kV Line"

    def excerpt(self) -> str:
        if self.source_url == FRCC_URL:
            head = ("FRCC 2026 Load and Resource Plan, Form 13 (proposed transmission lines "
                    f"as of January 1, 2026), page {self.page}")
        else:
            head = f"City of Tallahassee 2026 Ten Year Site Plan, Table 4.2, page {self.page}"
        return f"{head}: {self.row_text}{f' ({self.note})' if self.note else ''}"


def _in_service(month: int, year: int) -> tuple[date, str]:
    """Form 13 prints three FPL lines as '12/3033', a typo for 2033 (the plan runs
    2026-2035); read it as 2033 and say so."""
    if year > 2100 and str(year).startswith("3"):
        return date(year - 1000, month, 1), f"printed {month}/{year}; read as {year - 1000}"
    return date(year, month, 1), ""


def parse_form13_rows(rows: list[list[dict]], *, page: int) -> list[LineEntry]:
    """Rows of pdfplumber words (text, x0, x1), each sorted by x -> Form 13 entries."""
    entries = []
    for words in rows:
        if len(words) < 6 or not _OWNER.match(words[0]["text"]):
            continue
        texts = [w["text"] for w in words]
        miles_at = next((i for i in range(2, len(words)) if _NUMBER.match(texts[i])), None)
        if miles_at is None or miles_at < 3:
            continue
        tail = _TAIL.match(" ".join(texts[miles_at + 1:]))
        if not tail:
            continue
        terms = words[1:miles_at]
        gaps = [terms[i + 1]["x0"] - terms[i]["x1"] for i in range(len(terms) - 1)]
        split = gaps.index(max(gaps)) + 1
        when, note = _in_service(int(tail["month"]), int(tail["year"]))
        entries.append(LineEntry(
            page=page, source_url=FRCC_URL, owner_code=texts[0],
            terminal_a=" ".join(t["text"] for t in terms[:split]),
            terminal_b=" ".join(t["text"] for t in terms[split:]),
            miles=float(texts[miles_at]), in_service=when, voltage_kv=float(tail["kv"]),
            note=note, row_text=" ".join(texts),
        ))
    return entries


def _rows(page) -> list[list[dict]]:
    by_top: dict[int, list[dict]] = defaultdict(list)
    for w in page.extract_words():
        by_top[round(w["top"])].append(w)
    return [sorted(ws, key=lambda w: w["x0"]) for _, ws in sorted(by_top.items())]


def parse_frcc(path: Path) -> list[LineEntry]:
    import pdfplumber

    with pdfplumber.open(path) as pdf:
        return [e for n in FRCC_PAGES for e in parse_form13_rows(_rows(pdf.pages[n - 1]), page=n)]


# "Reconductor / Rebuild Line 20B Sub 16 7516 Bradfordville W (DEF) 3105 12/2030 115 3.08"
_TAL_ROW = re.compile(
    r"^(?P<kind>.+?)\s+Line\s+(?P<line>\w+)\s+(?P<a>.+?)\s+(?P<a_bus>\d{4})\s+(?P<b>.+?)\s+"
    r"(?P<b_bus>\d{4})\s+(?P<month>\d{1,2})/(?P<year>\d{4})\s+(?P<kv>\d+)\s+(?P<miles>[\d.]+)$"
)


def parse_tallahassee_text(text: str, *, page: int = TALLAHASSEE_PAGE) -> list[LineEntry]:
    entries = []
    for line in text.splitlines():
        if m := _TAL_ROW.match(line.strip()):
            when, note = _in_service(int(m["month"]), int(m["year"]))
            entries.append(LineEntry(
                page=page, source_url=TALLAHASSEE_URL, owner_code="TAL",
                terminal_a=m["a"], terminal_b=m["b"], miles=float(m["miles"]),
                in_service=when, voltage_kv=float(m["kv"]), note=note,
                row_text=f"{m['kind']}, Line {m['line']}: {line.strip()}",
            ))
    return entries


def parse_tallahassee(path: Path) -> list[LineEntry]:
    import pdfplumber

    with pdfplumber.open(path) as pdf:
        return parse_tallahassee_text(pdf.pages[TALLAHASSEE_PAGE - 1].extract_text() or "")
