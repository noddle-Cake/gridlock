"""Georgia Power 2025 IRP, Volume 3: "Table 2 Georgia ITS 10 Year Plan Project List".

The table (PDF pages 177-190 of the public-disclosure filing in the Sperry Tech challenge
kit) lists every project in the Georgia Integrated Transmission System ten-year plan:

    219 2027 19983 SAV: GOSHEN (SAV) - MCINTOSH 6/1/2027 SAV REDACTED REDACTED ...
    115KV LINE REBUILD

zone, year, TEAMS number, project name (wrapping onto the next lines), need date,
sponsor, then five cost columns that are redacted in the public version. Only the
unredacted fields are used. The page banner is a leftover from the CEII original; this
is the version Georgia Power filed publicly with the Georgia PSC.

Sponsors GPC and SAV (Georgia Power's Savannah zone) are Georgia Power's own projects.
GTC, MEAG and DU rows are other utilities' projects, which SERTP already lists, so they
are skipped here rather than loaded twice.

Project names follow the SERTP style ("A - B 115KV REBUILD"), so SERTP's title parsing
(endpoints, voltage, line vs substation) is reused.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from app.sources.sertp import SertpEntry

UTILITY = "Georgia Power"
# Georgia PSC Docket #56002 (Georgia Power 2025 IRP), linked from georgiapower.com's IRP
# page; Volume 3 is one of its filings and is the file in the Sperry challenge kit.
SOURCE_URL = "https://psc.ga.gov/search/facts-docket/?docketId=56002"
PAGES = range(177, 191)  # 1-based PDF pages holding Table 2
GPC_SPONSORS = {"GPC", "SAV"}
# Georgia plus the SC side of the Savannah River (Purrysburg, Thurmond Dam).
STATES = ["GA", "SC"]
BOUNDS = (30.3, 35.1, -85.7, -80.7)

_ROW = re.compile(
    r"^(?P<zone>\d{3}) (?P<year>\d{4}) (?P<teams>\d{4,6}) (?P<name>.*?) ?"
    r"(?P<need>\d{1,2}/\d{1,2}/\d{4}) (?P<sponsor>[A-Z]+) (?:REDACTED|\$)"
)
_SKIP = re.compile(
    r"^(PUBLIC DISCLOSURE|CRITICAL ENERGY|contents shall|policy, should|TEAMS Need|Zone Year|"
    r"Number 2024|Total\b|\d{4} GA ITS Ten-Year Plan|A\. Georgia ITS|Table 2)"
)


@dataclass
class ItsEntry:
    page: int
    zone: str
    teams: str
    name: str
    need: date
    sponsor: str

    def as_sertp(self) -> SertpEntry:
        """Same title conventions as SERTP; reuse its endpoint/voltage/kind parsing."""
        return SertpEntry(page=self.page, area="SOUTHERN", year=self.need.year,
                          name=self.name, description="", supporting="")

    def excerpt(self) -> str:
        return (f"Georgia ITS 10 Year Plan, Table 2 (zone {self.zone}, TEAMS {self.teams}): "
                f"{self.name}; need date {self.need:%m/%d/%Y}; sponsor {self.sponsor}. "
                "Cost columns are redacted in the public filing.")


def parse_lines(lines: list[tuple[int, str]]) -> list[ItsEntry]:
    """(page, text line) pairs in reading order -> table rows. A wrapped name continues on
    the following lines, possibly across a page break (headers in between are skipped)."""
    entries: list[ItsEntry] = []
    for page, raw in lines:
        line = raw.strip()
        if not line or _SKIP.match(line):
            continue
        if m := _ROW.match(line):
            month, day, year = (int(x) for x in m["need"].split("/"))
            entries.append(ItsEntry(page=page, zone=m["zone"], teams=m["teams"],
                                    name=m["name"].strip(), need=date(year, month, day),
                                    sponsor=m["sponsor"]))
        elif entries:
            entries[-1].name = f"{entries[-1].name} {line}"
    for e in entries:
        e.name = re.sub(r"\s+", " ", e.name).strip()
        e.name = re.sub(r"(\w)- (\w)", r"\1 - \2", e.name)  # "BONAIRE PRI- ECHECONNEE"
    return entries


def parse_report(path: Path, *, sponsors: set[str] | None = GPC_SPONSORS) -> list[ItsEntry]:
    import pdfplumber

    lines: list[tuple[int, str]] = []
    with pdfplumber.open(path) as pdf:
        for page_no in PAGES:
            text = pdf.pages[page_no - 1].extract_text() or ""
            lines += [(page_no, ln) for ln in text.splitlines()]
    entries = parse_lines(lines)
    return [e for e in entries if sponsors is None or e.sponsor in sponsors]
