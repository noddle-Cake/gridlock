"""Load structured public sources straight into the projects table (no LLM needed).

    python -m scripts.load_public_sources eia860m                 # nationwide
    python -m scripts.load_public_sources eia860m --states GA AL TN
    python -m scripts.load_public_sources sertp                   # all 7 SERTP areas
    python -m scripts.load_public_sources sertp --areas SOUTHERN TVA
    python -m scripts.load_public_sources all --dry-run          # parse + CSV only

Inputs default to the raw copies in source_docs/. Every run writes a citation table to
source_docs/extracted/ (one row per project: source file, page/sheet, rows, excerpt) and,
unless --dry-run, replaces that source's previous load in DATABASE_URL.

SERTP location lookups use the committed caches (app/data/osm_substations.csv,
app/data/place_cache.json); --offline skips network lookups for names not yet cached.
"""

from __future__ import annotations

import argparse
import asyncio
import csv
from collections import Counter
from datetime import date
from pathlib import Path

from app.core.config import get_settings
from app.db import repository as repo
from app.db.pool import apply_schema, create_pool
from app.models.enums import DatePrecision, ProjectType
from app.sources import eia860m, sertp, snapshot
from app.sources.locate import PlaceCache, locate

ROOT = Path(__file__).resolve().parents[2]
DOCS = ROOT / "source_docs"
EXTRACTED = DOCS / "extracted"

EXPORT_COLUMNS = [
    "utility", "state", "name", "type", "voltage_kv", "in_service", "lat", "lng", "route",
    "approximate", "requires_review", "confidence", "location_ref", "source_file",
    "source_url", "source_page", "raw_excerpt",
]


def write_export(path: Path, projects: list[repo.NewProject], source_file: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=EXPORT_COLUMNS, lineterminator="\n")
        w.writeheader()
        for p in projects:
            in_service = p.start_date.strftime("%Y-%m" if p.start_precision ==
                                               DatePrecision.MONTH else "%Y")
            w.writerow({
                "utility": p.utility, "state": p.state or "", "name": p.name,
                "type": p.type.value if p.type else "", "voltage_kv": p.voltage_kv or "",
                "in_service": in_service, "lat": p.lat if p.lat is not None else "",
                "lng": p.lng if p.lng is not None else "",
                "route": snapshot.format_route(p.route), "approximate": p.approximate,
                "requires_review": p.requires_review, "confidence": p.confidence,
                "location_ref": p.location_ref, "source_file": source_file,
                "source_url": p.source_url, "source_page": p.source_page,
                "raw_excerpt": p.raw_excerpt,
            })
    print(f"wrote {len(projects)} rows -> {path.relative_to(ROOT)}")


# ---------------------------------------------------------------- EIA-860M


def eia_projects(path: Path, states: list[str] | None) -> list[repo.NewProject]:
    plants = eia860m.parse_planned(path, states=states)
    out = []
    for p in plants:
        month = date(p.year, p.month, 1)
        out.append(repo.NewProject(
            utility=p.utility, state=p.state, name=p.name, type=ProjectType.GENERATION,
            voltage_kv=None, location_ref=p.location_ref, lat=p.lat, lng=p.lng,
            start_date=month, end_date=month, start_precision=DatePrecision.MONTH,
            end_precision=DatePrecision.MONTH,
            confidence=1.0,  # read verbatim from a structured federal dataset
            source_url=eia860m.SOURCE_URL, source_page=p.sheet_index,
            raw_excerpt=p.excerpt(),
        ))
    gens = sum(len(p.generators) for p in plants)
    print(f"EIA-860M: {gens} planned generators -> {len(out)} plant/in-service-month projects "
          f"({len({p.utility for p in plants})} owners)")
    return out


# ---------------------------------------------------------------- SERTP


def sertp_projects(path: Path, areas: set[str] | None, *, offline: bool) -> list[repo.NewProject]:
    entries = sertp.parse_report(path, areas=areas)
    places = PlaceCache(offline=offline, user_agent=get_settings().geocoder_user_agent)
    out = []
    stats: Counter[str] = Counter()
    try:
        for i, e in enumerate(entries, start=1):
            where = locate(e.endpoints, e.states, places, operator=e.owner,
                           bounds=sertp.AREA_BOUNDS.get(e.area))
            stats["review" if where.requires_review else
                  "approximate" if where.approximate else "exact"] += 1
            if i % 50 == 0:
                places.save()
                print(f"  located {i}/{len(entries)}: {dict(stats)}")
            year = date(e.year, 1, 1)
            confidence = 0.6 if where.requires_review else 0.8 if where.approximate else 0.95
            state = e.states[0] if len(e.states) == 1 else None
            out.append(repo.NewProject(
                utility=e.owner, state=state, name=e.title.title(),
                type=ProjectType(e.kind), voltage_kv=e.voltage_kv,
                location_ref=" - ".join(n.title() for n in e.endpoints) +
                f" ({'/'.join(e.states)})",
                lat=where.lat, lng=where.lng, approximate=where.approximate,
                requires_review=where.requires_review,
                route=where.ends if e.kind == "transmission line" else None,
                start_date=year, end_date=year, start_precision=DatePrecision.YEAR,
                end_precision=DatePrecision.YEAR, confidence=confidence,
                source_url=sertp.SOURCE_URL, source_page=e.page,
                raw_excerpt=(f"SERTP {e.area} Balancing Authority Area, page {e.page}.\n"
                             f"{e.excerpt()}\n{where.how}")[:2000],
            ))
    finally:
        places.save()
    print(f"SERTP: {len(entries)} projects; location {dict(stats)}")
    print("  by owner:", dict(Counter(p.utility for p in out).most_common()))
    return out


# ---------------------------------------------------------------- main


async def load(source: snapshot.Source, projects: list[repo.NewProject], csv_path: Path) -> None:
    pool = await create_pool(get_settings().database_url)
    try:
        await apply_schema(pool)
        async with pool.acquire() as conn:
            # Record the CSV's hash so app startup sees this load as current.
            plan_id = await snapshot.save(conn, source, projects, snapshot.file_sha(csv_path))
        print(f"loaded {len(projects)} projects as plan {plan_id} ({source.label})")
    finally:
        await pool.close()


def main() -> None:
    ap = argparse.ArgumentParser(description="Load EIA-860M / SERTP public data.")
    ap.add_argument("source", choices=["eia860m", "sertp", "all"])
    ap.add_argument("--eia-file", type=Path, default=DOCS / snapshot.EIA860M.filename)
    ap.add_argument("--sertp-file", type=Path, default=DOCS / snapshot.SERTP.filename)
    ap.add_argument("--states", nargs="+", default=["ALL"],
                    help="EIA-860M plant states (default ALL = nationwide)")
    ap.add_argument("--areas", nargs="+", help=f"SERTP areas, default all: {list(sertp.AREAS)}")
    ap.add_argument("--offline", action="store_true", help="no Nominatim calls for SERTP")
    ap.add_argument("--dry-run", action="store_true", help="parse + write CSV, skip the DB")
    args = ap.parse_args()

    if args.source in ("eia860m", "all"):
        states = None if [s.upper() for s in args.states] == ["ALL"] else args.states
        projects = eia_projects(args.eia_file, states)
        out = EXTRACTED / snapshot.EIA860M.export
        write_export(out, projects, args.eia_file.name)
        if not args.dry_run:
            asyncio.run(load(snapshot.EIA860M, projects, out))

    if args.source in ("sertp", "all"):
        areas = {a.upper() for a in args.areas} if args.areas else None
        projects = sertp_projects(args.sertp_file, areas, offline=args.offline)
        out = EXTRACTED / snapshot.SERTP.export
        write_export(out, projects, args.sertp_file.name)
        if not args.dry_run:
            asyncio.run(load(snapshot.SERTP, projects, out))


if __name__ == "__main__":
    main()
