"""Generate sample capital plans and (optionally) seed the database with their projects.

    python -m scripts.seed_demo --files-only   # write sample_data/*.pdf|csv|xlsx
    python -m scripts.seed_demo                # also load demo projects into DATABASE_URL

Seeding inserts pre-extracted projects directly (what extraction + geocoding would
produce), so the demo loop works without a Gemini key. To exercise the real pipeline,
upload the generated files through the UI or POST /ingest instead.

All utilities below are fictional; the towns and counties are real.
"""

from __future__ import annotations

import argparse
import asyncio
import csv
from dataclasses import dataclass
from pathlib import Path

from app.core.config import get_settings
from app.db import repository as repo
from app.db.pool import apply_schema, create_pool
from app.models.enums import PlanStatus, ProjectType
from app.models.partial_date import PartialDate

ROOT = Path(__file__).resolve().parents[2]
SAMPLE_DIR = ROOT / "sample_data"
SAMPLE_BASE_URL = "http://localhost:8000/samples"

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

    def excerpt(self) -> str:
        kv = f"{self.kv:g} kV " if self.kv else ""
        kind = self.type.value if self.type else "project"
        return (f"{self.name}. {kv}{kind} work at {self.location}. "
                f"Planned in-service window: {self.start} through {self.end}.")


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

COLUMNS = ["Project", "Category", "Voltage (kV)", "Location", "Start", "End"]


def _row(p: Demo) -> list[str]:
    return [p.name, p.type.value if p.type else "", f"{p.kv:g}" if p.kv else "", p.location,
            p.start, p.end]


def write_pdf(path: Path, utility: str, projects: list[Demo]) -> None:
    from reportlab.lib.pagesizes import letter
    from reportlab.pdfgen import canvas

    c = canvas.Canvas(str(path), pagesize=letter)
    c.setFont("Helvetica-Bold", 20)
    c.drawString(72, 700, f"{utility}")
    c.setFont("Helvetica", 14)
    c.drawString(72, 676, "Five-Year Transmission & Substation Capital Plan, 2026-2030")
    c.drawString(72, 652, "Public filing. Project list begins on page 2.")
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


def write_files() -> None:
    SAMPLE_DIR.mkdir(exist_ok=True)
    for utility, plan in PLANS.items():
        path = SAMPLE_DIR / plan["file"]
        if path.suffix == ".pdf":
            write_pdf(path, utility, plan["projects"])
        elif path.suffix == ".csv":
            write_csv(path, plan["projects"])
        else:
            write_xlsx(path, plan["projects"])
        print(f"wrote {path.relative_to(ROOT)}")


async def seed(reset: bool) -> None:
    pool = await create_pool(get_settings().database_url)
    await apply_schema(pool)
    async with pool.acquire() as conn, conn.transaction():
        if reset:
            await conn.execute("TRUNCATE briefs, projects, plans RESTART IDENTITY CASCADE")
        for utility, plan in PLANS.items():
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
                    raw_excerpt=p.excerpt(),
                ))
            await repo.insert_projects(conn, rows)
            await repo.set_plan_status(conn, dto.plan_id, PlanStatus.COMPLETE,
                                       project_count=len(rows))
            print(f"seeded {len(rows)} projects for {utility}")
    await pool.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--files-only", action="store_true", help="only write sample files")
    parser.add_argument("--no-reset", action="store_true", help="keep existing data")
    args = parser.parse_args()
    write_files()
    if not args.files_only:
        asyncio.run(seed(reset=not args.no_reset))


if __name__ == "__main__":
    main()
