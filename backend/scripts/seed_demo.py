"""Generate sample capital plans and (optionally) seed the database with their projects.

    python -m scripts.seed_demo --files-only   # write sample_data/*.pdf|csv|xlsx
    python -m scripts.seed_demo --db-only      # load demo projects, keep existing files
    python -m scripts.seed_demo                # also load demo projects into DATABASE_URL
    python -m scripts.seed_demo --region fl-ga # FL–GA border set (illustrative projects)

Seeding inserts pre-extracted projects directly (what extraction + geocoding would
produce), so the demo loop works without a Gemini key. To exercise the real pipeline,
upload the generated files through the UI or POST /ingest instead.

All utilities below are fictional; the towns and counties are real.
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import os
from dataclasses import dataclass
from pathlib import Path

from app.core.config import get_settings
from app.db import repository as repo
from app.db.pool import apply_schema, create_pool
from app.models.enums import PlanStatus, ProjectType
from app.models.partial_date import PartialDate

ROOT = Path(__file__).resolve().parents[2]
SAMPLE_DIR = ROOT / "sample_data"
# Where the browser can fetch sample_data/: the API directly in dev, "/api/samples" behind
# the production reverse proxy (docker-compose.prod.yml sets it).
SAMPLE_BASE_URL = os.environ.get("SAMPLE_BASE_URL", "http://localhost:8000/samples")

SUB, LINE, GEN = ProjectType.SUBSTATION, ProjectType.TRANSMISSION_LINE, ProjectType.GENERATION


@dataclass
class Demo:
    name: str
    type: ProjectType | None
    kv: float | None
    location: str
    start: str
    end: str
    page: int
    lat: float | None
    lng: float | None
    confidence: float
    approximate: bool = False
    state: str = ""

    def excerpt(self, note: str = "") -> str:
        kv = f"{self.kv:g} kV " if self.kv else ""
        kind = self.type.value if self.type else "project"
        window = (f"Planned in-service window: {self.start} through {self.end}."
                  if self.start or self.end else "Schedule not published.")
        return f"{note}{self.name}. {kv}{kind} work at {self.location}. {window}"


PLANS: dict[str, dict] = {
    "Keystone Electric": {
        "file": "keystone_electric_capital_plan.pdf",
        "state": "PA",
        "projects": [
            Demo("Hanover 115 kV breaker replacement", SUB, 115, "Hanover, PA", "Q2 2026",
                 "Q3 2026", 2, 39.8007, -76.9830, 0.93),
            Demo("Gettysburg–Littlestown 115 kV line rebuild", LINE, 115, "Littlestown, PA",
                 "2026", "2027", 2, 39.7443, -77.0880, 0.88),
            Demo("Shrewsbury 69 kV substation expansion", SUB, 69, "Shrewsbury, PA", "Q1 2027",
                 "Q4 2027", 3, 39.7687, -76.6797, 0.81),
            Demo("Red Lion solar interconnection (20 MW)", GEN, 34.5, "Red Lion, PA", "2027",
                 "2027", 3, 39.9009, -76.6058, 0.74),
            Demo("York North 230 kV transformer replacement", SUB, 230, "York, PA", "Q3 2026",
                 "Q4 2026", 4, 39.9626, -76.7277, 0.9),
            Demo("Adams County reliability upgrades", SUB, 69, "Adams County, PA", "2026",
                 "2026", 4, 39.8715, -77.2177, 0.62, approximate=True),
            Demo("Chambersburg 138 kV substation (new)", SUB, 138, "Chambersburg, PA", "2028",
                 "2028", 5, 39.9376, -77.6611, 0.86),
            Demo("Waynesboro battery storage", GEN, None, "Waynesboro, PA", "Q4 2026",
                 "Q2 2027", 5, 39.7565, -77.5780, 0.55),
            Demo("Mason-Dixon tap rebuild", LINE, 115, "Mason-Dixon Tap", "2027", "2027", 5,
                 None, None, 0.48),
        ],
    },
    "Chesapeake Power": {
        "file": "chesapeake_power_capital_plan.csv",
        "state": "MD",
        "projects": [
            Demo("Westminster 115 kV breaker upgrade", SUB, 115, "Westminster, MD", "2026-05",
                 "2026-10", 1, 39.5754, -76.9958, 0.91),
            Demo("Manchester 115 kV relay retrofit", SUB, 115, "Manchester, MD", "Q3 2026",
                 "Q3 2026", 1, 39.6612, -76.8850, 0.87),
            Demo("Taneytown–Emmitsburg 115 kV line rebuild", LINE, 115, "Taneytown, MD",
                 "2026", "2027", 1, 39.6576, -77.1747, 0.84),
            Demo("Hampstead solar interconnection", GEN, 34.5, "Hampstead, MD", "2027", "2027",
                 1, 39.6048, -76.8497, 0.69),
            Demo("Frederick 230 kV substation", SUB, 230, "Frederick, MD", "2029", "2029", 1,
                 39.4143, -77.4105, 0.92),
            Demo("Carroll County substation hardening", SUB, 69, "Carroll County, MD",
                 "Q1 2027", "Q2 2027", 1, 39.5629, -77.0225, 0.58, approximate=True),
            Demo("Hagerstown 138 kV substation rebuild", SUB, 138, "Hagerstown, MD", "2028",
                 "2028", 1, 39.6418, -77.7200, 0.89),
        ],
    },
    "Susquehanna Grid": {
        "file": "susquehanna_grid_capital_plan.xlsx",
        "state": "PA",
        "projects": [
            Demo("Red Lion 69 kV substation upgrade", SUB, 69, "Red Lion, PA", "Q2 2027",
                 "Q3 2027", 1, 39.9009, -76.6058, 0.9),
            Demo("York 230 kV line reconductor", LINE, 230, "York, PA", "Q3 2026", "Q4 2026",
                 1, 39.9700, -76.7000, 0.83),
            Demo("Glen Rock switching station", SUB, None, "Glen Rock", "2027", "", 1,
                 None, None, 0.41),
        ],
    },
}

# Florida–Georgia border. ILLUSTRATIVE ONLY: the utilities and towns are real, but these
# projects are invented placeholders (not taken from any filing) positioned to exercise
# every overlap tier on top of the real HIFLD lines. Replace them by ingesting the
# utilities' actual plans (SERTP / GA IRP, FL PSC Ten-Year Site Plans).
# Planted pairs (25 mi / 30 day defaults):
#   crossing  GPC Kingsland–St. Marys line  x  FPL Yulee–Kingsland line      (~0.1 km)
#   < 1.6 km  GPC Valdosta substation       x  GTC Valdosta South            (~1.3 km)
#   < 8 km    FPL Nassau substation         x  JEA Oceanway substation       (~6 km)
#   < 40 km   FPL Chattahoochee x GPC Bainbridge; Duke Monticello x GPC Boston;
#             Duke Madison x GTC Quitman
#   near-miss Tallahassee #34 x GPC Thomasville (~45 km, same window: not flagged);
#             JEA Northside x FPL Nassau (close, but 2029 vs 2027: not flagged)
DEMO_NOTE = "ILLUSTRATIVE DEMO PROJECT, not from an actual utility filing. "

PLANS_FL_GA: dict[str, dict] = {
    "Georgia Power": {
        "file": "demo_fl-ga_georgia_power.pdf",
        "state": "GA",
        "projects": [
            Demo("Kingsland–St. Marys River 230 kV line rebuild", LINE, 230, "Kingsland, GA",
                 "Q1 2027", "Q4 2027", 2, 30.7440, -81.6980, 0.9),
            Demo("Valdosta 230/115 kV substation expansion", SUB, 230, "Valdosta, GA",
                 "Q2 2027", "Q1 2028", 2, 30.8327, -83.2785, 0.92),
            Demo("Thomasville 115 kV breaker replacement", SUB, 115, "Thomasville, GA",
                 "Q3 2026", "Q4 2026", 3, 30.8366, -83.9788, 0.88),
            Demo("Bainbridge 115 kV line reconductor", LINE, 115, "Bainbridge, GA", "2028",
                 "2028", 3, 30.9038, -84.5755, 0.83),
            Demo("Waycross 500 kV substation (new)", SUB, 500, "Waycross, GA", "2029", "2030",
                 4, 31.2136, -82.3540, 0.86),
            Demo("Boston 115 kV switching station", SUB, 115, "Boston, GA", "Q1 2028",
                 "Q3 2028", 4, 30.7916, -83.7896, 0.79),
        ],
    },
    "Florida Power & Light": {
        "file": "demo_fl-ga_fpl.xlsx",
        "state": "FL",
        "projects": [
            Demo("Yulee–Kingsland 230 kV interconnection rebuild", LINE, 230, "Yulee, FL",
                 "Q2 2027", "Q2 2028", 1, 30.7432, -81.6975, 0.87),
            Demo("Nassau 230 kV substation upgrade", SUB, 230, "Callahan, FL", "Q4 2026",
                 "Q3 2027", 1, 30.5200, -81.6200, 0.9),
            Demo("Marianna 115 kV substation rebuild", SUB, 115, "Marianna, FL", "2027", "2027",
                 1, 30.7744, -85.2269, 0.85),
            Demo("Chipley 115 kV line rebuild", LINE, 115, "Chipley, FL", "2029", "2029", 1,
                 30.7816, -85.5385, 0.8),
            Demo("Chattahoochee 230 kV breaker upgrade", SUB, 230, "Chattahoochee, FL",
                 "Q1 2028", "Q2 2028", 1, 30.7052, -84.8458, 0.84),
        ],
    },
    "Duke Energy Florida": {
        "file": "demo_fl-ga_duke_energy_florida.csv",
        "state": "FL",
        "projects": [
            Demo("Madison 115 kV substation upgrade", SUB, 115, "Madison, FL", "Q3 2027",
                 "Q2 2028", 1, 30.4694, -83.4129, 0.86),
            Demo("Monticello 115 kV line rebuild", LINE, 115, "Monticello, FL", "Q2 2028",
                 "Q4 2028", 1, 30.5452, -83.8710, 0.82),
            Demo("Jasper 69 kV substation retirement", SUB, 69, "Jasper, FL", "2026", "2026",
                 1, 30.5183, -82.9482, 0.7),
            Demo("Hamilton County reliability upgrades", SUB, 115, "Hamilton County, FL",
                 "2030", "2030", 1, 30.4966, -82.9480, 0.6, approximate=True),
        ],
    },
    "JEA": {
        "file": "demo_fl-ga_jea.csv",
        "state": "FL",
        "projects": [
            Demo("Oceanway 230 kV substation (new)", SUB, 230, "Oceanway, Jacksonville, FL",
                 "Q1 2027", "Q4 2027", 1, 30.4700, -81.6400, 0.91),
            Demo("Northside 138 kV line reconductor", LINE, 138, "Northside, Jacksonville, FL",
                 "2029", "2030", 1, 30.4300, -81.5500, 0.85),
            Demo("Cecil Commerce Center 230 kV substation", SUB, 230, "Cecil, Jacksonville, FL",
                 "2028", "2028", 1, 30.2190, -81.8760, 0.78),
        ],
    },
    "Georgia Transmission Corp": {
        "file": "demo_fl-ga_georgia_transmission.pdf",
        "state": "GA",
        "projects": [
            Demo("Valdosta South 115 kV substation", SUB, 115, "Valdosta, GA", "Q3 2027",
                 "Q2 2028", 2, 30.8220, -83.2850, 0.88),
            Demo("Quitman 115 kV tap line", LINE, 115, "Quitman, GA", "Q1 2028", "Q4 2028", 2,
                 30.7849, -83.5599, 0.84),
            Demo("Homerville 230 kV switching station", SUB, 230, "Homerville, GA", "2030",
                 "2030", 3, 31.0368, -82.7471, 0.8),
            Demo("Kingsland area 230 kV capacitor bank", SUB, 230, "Kingsland area", "", "", 3,
                 None, None, 0.45),
        ],
    },
    "City of Tallahassee": {
        "file": "demo_fl-ga_city_of_tallahassee.xlsx",
        "state": "FL",
        "projects": [
            Demo("Substation 34 115 kV (new)", SUB, 115, "Tallahassee, FL", "Q3 2026",
                 "Q1 2027", 1, 30.4383, -84.2807, 0.83),
            Demo("Hopkins–Boston 230 kV tie line study", LINE, 230, "Tallahassee, FL", "2028",
                 "2029", 1, 30.4800, -84.3600, 0.77),
        ],
    },
}

REGIONS: dict[str, tuple[dict[str, dict], str]] = {
    "pa": (PLANS, ""),
    "fl-ga": (PLANS_FL_GA, DEMO_NOTE),
}

COLUMNS = ["Project", "Category", "Voltage (kV)", "Location", "Start", "End"]


def _row(p: Demo) -> list[str]:
    return [p.name, p.type.value if p.type else "", f"{p.kv:g}" if p.kv else "", p.location,
            p.start, p.end]


def write_pdf(path: Path, utility: str, projects: list[Demo], note: str = "") -> None:
    from reportlab.lib.pagesizes import letter
    from reportlab.pdfgen import canvas

    c = canvas.Canvas(str(path), pagesize=letter)
    c.setFont("Helvetica-Bold", 20)
    c.drawString(72, 700, f"{utility}")
    c.setFont("Helvetica", 14)
    c.drawString(72, 676, "Five-Year Transmission & Substation Capital Plan, 2026-2030")
    c.drawString(72, 652, note.strip() if note else "Public filing. Project list begins on page 2.")
    c.showPage()
    for page in sorted({p.page for p in projects}):
        c.setFont("Helvetica-Bold", 13)
        c.drawString(72, 720, f"Capital projects (page {page})")
        y = 690
        for p in (p for p in projects if p.page == page):
            c.setFont("Helvetica-Bold", 11)
            c.drawString(72, y, p.name)
            c.setFont("Helvetica", 10)
            kv = f"{p.kv:g} kV" if p.kv else "voltage TBD"
            kind = p.type.value if p.type else "project"
            c.drawString(90, y - 15, f"Category: {kind}.  Voltage: {kv}.  Location: {p.location}.")
            c.drawString(90, y - 29, f"Schedule: {p.start} through {p.end}.")
            y -= 60
        c.showPage()
    c.save()


def write_csv(path: Path, projects: list[Demo]) -> None:
    with path.open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(COLUMNS)
        w.writerows(_row(p) for p in projects)


def write_xlsx(path: Path, projects: list[Demo]) -> None:
    from openpyxl import Workbook

    wb = Workbook()
    ws = wb.active
    ws.title = "Capital Plan"
    ws.append(COLUMNS)
    for p in projects:
        ws.append(_row(p))
    wb.save(path)


def write_files(region: str) -> None:
    plans, note = REGIONS[region]
    SAMPLE_DIR.mkdir(exist_ok=True)
    for utility, plan in plans.items():
        path = SAMPLE_DIR / plan["file"]
        if path.suffix == ".pdf":
            write_pdf(path, utility, plan["projects"], note)
        elif path.suffix == ".csv":
            write_csv(path, plan["projects"])
        else:
            write_xlsx(path, plan["projects"])
        print(f"wrote {path.relative_to(ROOT)}")


async def seed(region: str, reset: bool) -> None:
    plans, note = REGIONS[region]
    pool = await create_pool(get_settings().database_url)
    await apply_schema(pool)
    async with pool.acquire() as conn, conn.transaction():
        if reset:
            await conn.execute("TRUNCATE briefs, projects, plans RESTART IDENTITY CASCADE")
        for utility, plan in plans.items():
            ext = plan["file"].rsplit(".", 1)[1]
            source_url = f"{SAMPLE_BASE_URL}/{plan['file']}"
            dto = await repo.insert_plan(conn, utility=utility, source_url=source_url,
                                         filename=plan["file"], detected_format=ext)
            rows = []
            for p in plan["projects"]:
                start, end = PartialDate.parse(p.start), PartialDate.parse(p.end)
                rows.append(repo.NewProject(
                    plan_id=dto.plan_id, utility=utility, state=plan["state"], name=p.name,
                    type=p.type, voltage_kv=p.kv, location_ref=p.location, lat=p.lat,
                    lng=p.lng, approximate=p.approximate, requires_review=p.lat is None,
                    start_date=start.materialize()[0] if start else None,
                    end_date=end.materialize()[1] if end else None,
                    start_precision=start.precision if start else None,
                    end_precision=end.precision if end else None,
                    confidence=p.confidence, source_url=source_url, source_page=p.page,
                    raw_excerpt=p.excerpt(note),
                ))
            await repo.insert_projects(conn, rows)
            await repo.set_plan_status(conn, dto.plan_id, PlanStatus.COMPLETE,
                                       project_count=len(rows))
            print(f"seeded {len(rows)} projects for {utility}")
    await pool.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--files-only", action="store_true", help="only write sample files")
    parser.add_argument("--db-only", action="store_true",
                        help="only seed the database (sample files already exist)")
    parser.add_argument("--no-reset", action="store_true", help="keep existing data")
    parser.add_argument("--region", choices=[*REGIONS, "all"], default="pa",
                        help="demo set: pa (fictional utilities), fl-ga (illustrative "
                             "projects for real FL/GA utilities), or all")
    args = parser.parse_args()
    regions = list(REGIONS) if args.region == "all" else [args.region]
    for i, region in enumerate(regions):
        if not args.db_only:
            write_files(region)
        if not args.files_only:
            # Only the first region may reset, so "all" loads every set.
            asyncio.run(seed(region, reset=not args.no_reset and i == 0))


if __name__ == "__main__":
    main()
