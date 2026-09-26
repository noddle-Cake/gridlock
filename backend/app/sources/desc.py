"""Dominion Energy South Carolina: "Planned Transmission Projects $2M and above" -> records.

The PDF (DESC's SCRTP 2024-2028 project descriptions, from the Sperry Tech challenge kit)
is one project per page, laid out as

    Project 23 of 44
    Dominion Energy South Carolina
    Planned Transmission Projects $2M and above Total
    5 Year Budget
    Jasper – Okatie 230 kV #2: Construct
    Project ID / <id>
    Project Description / <text>
    Project Need / <text>
    Project Status / In Progress
    Planned In-Service Date / 12/31/25
    Estimated Project Cost
    Previous 2024 2025 2026 2027 2028 Total*
    $0 $1,000,000 ... $23,787,423

which pdfplumber reads cleanly, so this is a deterministic parser (no LLM call).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

UTILITY = "Dominion Energy South Carolina"
# Published by SCRTP (South Carolina Regional Transmission Planning), where DESC posts its
# planned project lists; the same file is in the Sperry challenge kit.
SOURCE_URL = (
    "https://www.scrtp.com/assets/pdfs/home/2024-2028-2million-and-above-project-descriptions.pdf"
)
# Planned lines can end in Georgia (Stevens Creek hydro in Martinez, GA; Thurmond Dam).
STATES = ["SC", "GA"]
# DESC's territory plus the Savannah-river side of Georgia (min lat, max lat, min lng, max lng).
BOUNDS = (31.9, 35.3, -83.5, -78.5)

_HEADINGS = ["Project ID", "Project Description", "Project Need", "Project Status",
             "Planned In-Service Date", "Estimated Project Cost"]
_DATE = re.compile(r"\b(\d{1,2})/(\d{1,2})/(\d{2}|\d{4})\b")
_MONEY = re.compile(r"\$[\d,]+")
_KV = re.compile(r"(\d{2,3}(?:\.\d+)?)(?:\s*[-/]\s*\d{1,3}(?:\.\d+)?)*\s*kV", re.I)
# Words after the place names in a title segment ("Riverport Tap", "Harleyville
# Transmission Tap", "Edenwood Sub").
_TAIL = re.compile(
    r"\s+(sub(station)?|transmission|tap|line|tie|loop|reservoir crossings?|rebuild|rebld|"
    r"construct|fold-in|spdc)\b.*$", re.I,
)
_LINE_WORDS = re.compile(r"\b(line|tap|tie|loop|fold-in|rebuild|rebld|spdc|section)\b", re.I)


@dataclass
class DescEntry:
    page: int
    title: str
    project_id: str
    description: str
    need: str
    status: str
    in_service_text: str
    costs: list[int] = field(default_factory=list)  # Previous, 2024 ... 2028, Total

    @property
    def in_service(self) -> tuple[date, date] | None:
        """First and last date in the field ("10/1/2025 (phase 1) and 10/1/2026 (phase 2)")."""
        found = []
        for m, d, y in _DATE.findall(self.in_service_text):
            year = int(y) + 2000 if len(y) == 2 else int(y)
            found.append(date(year, int(m), int(d)))
        return (min(found), max(found)) if found else None

    @property
    def cost_usd(self) -> int | None:
        return self.costs[-1] if self.costs else None

    @property
    def voltage_kv(self) -> float | None:
        found = [float(v) for v in _KV.findall(self.title)]
        return max(found) if found else None

    @property
    def endpoints(self) -> list[str]:
        """Place names the title starts with: 'Jasper – Okatie 230 kV #2: Construct' ->
        ['Jasper', 'Okatie']; 'Edenwood Sub: #1 ...' -> ['Edenwood']."""
        head = self.title.split(":")[0]
        head = re.sub(r"\(.*?\)", " ", head)
        head = re.split(r",|&|\band\b|/", head)[0]
        if m := _KV.search(head):
            head = head[:m.start()]
        names = []
        for part in re.split(r"\s*[-–]\s*", head):
            part = _TAIL.sub("", part.strip()).strip()
            if len(part) >= 3 and not part.lower().startswith(("construct", "rebuild")):
                names.append(part)
        return list(dict.fromkeys(names))

    @property
    def kind(self) -> str:
        if len(self.endpoints) >= 2 or _LINE_WORDS.search(self.title):
            return "transmission line"
        return "substation"

    def excerpt(self) -> str:
        costs = ", ".join(f"${c:,}" for c in self.costs)
        return (
            f"{self.title}\nProject ID: {self.project_id}\nDescription: {self.description}\n"
            f"Need: {self.need}\nStatus: {self.status}\n"
            f"Planned In-Service Date: {self.in_service_text}\n"
            f"Estimated cost (Previous, 2024-2028, Total): {costs}"
        )


def _clean(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def parse_page_text(text: str, *, page: int) -> DescEntry | None:
    lines = [ln.strip() for ln in text.splitlines()]
    try:
        start = lines.index("5 Year Budget") + 1
        idx = {h: lines.index(h) for h in _HEADINGS}
    except ValueError:
        return None

    def section(heading: str) -> str:
        i = idx[heading] + 1
        later = [j for j in idx.values() if j >= i]
        return _clean(" ".join(lines[i:min(later) if later else len(lines)]))

    cost_line = next((ln for ln in lines[idx["Estimated Project Cost"]:] if ln.startswith("$")),
                     "")
    return DescEntry(
        page=page, title=_clean(" ".join(lines[start:idx["Project ID"]])),
        project_id=section("Project ID"), description=section("Project Description"),
        need=section("Project Need"), status=section("Project Status"),
        in_service_text=section("Planned In-Service Date"),
        costs=[int(m.replace("$", "").replace(",", "")) for m in _MONEY.findall(cost_line)],
    )


def parse_report(path: Path) -> list[DescEntry]:
    import pdfplumber

    entries = []
    with pdfplumber.open(path) as pdf:
        for page_no, page in enumerate(pdf.pages, start=1):
            entry = parse_page_text(page.extract_text() or "", page=page_no)
            if entry:
                entries.append(entry)
    return entries
