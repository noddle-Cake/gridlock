"""Load structured public sources straight into the projects table (no LLM needed).

    python -m scripts.load_public_sources eia860m                 # nationwide
    python -m scripts.load_public_sources eia860m --states GA AL TN
    python -m scripts.load_public_sources sertp                   # every SERTP project
    python -m scripts.load_public_sources sertp --areas SOUTHERN DUKE CAROLINAS
    python -m scripts.load_public_sources all --states SC GA FL   # the Sperry region only
    python -m scripts.load_public_sources desc                    # DESC $2M+ projects
    python -m scripts.load_public_sources gpc                     # Georgia Power ITS list
    python -m scripts.load_public_sources all --dry-run          # parse + CSV only

Everything is kept by default. --states narrows EIA-860M to plants in those states and SERTP
to projects located there (app/sources/region.py; the Sperry region is SC GA FL). Inputs
default to the raw copies in source_docs/. Every run writes a citation table to
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
from dataclasses import replace
from datetime import date
from pathlib import Path

from app.core.config import get_settings
from app.db import repository as repo
from app.db.pool import apply_schema, create_pool
from app.models.enums import DatePrecision, ProjectType
from app.services.names import title_case
from app.sources import desc, eia860m, florida, gpc_its, region, sertp, snapshot
from app.sources.locate import PlaceCache, locate

ROOT = Path(__file__).resolve().parents[2]
DOCS = ROOT / "source_docs"
EXTRACTED = DOCS / "extracted"

EXPORT_COLUMNS = [
    "utility", "state", "name", "type", "voltage_kv", "in_service", "in_service_end", "lat",
    "lng", "route", "cost_usd", "approximate", "requires_review", "confidence", "location_ref",
    "source_file", "source_url", "source_page", "raw_excerpt",
]


def write_export(path: Path, projects: list[repo.NewProject], source_file: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=EXPORT_COLUMNS, lineterminator="\n")
        w.writeheader()
        for p in projects:
            fmt = {DatePrecision.DAY: "%Y-%m-%d", DatePrecision.MONTH: "%Y-%m"}.get(
                p.start_precision, "%Y")
            in_service = p.start_date.strftime(fmt)
            in_service_end = p.end_date.isoformat() if p.end_date != p.start_date else ""
            w.writerow({
                "utility": p.utility, "state": p.state or "", "name": p.name,
                "type": p.type.value if p.type else "", "voltage_kv": p.voltage_kv or "",
                "in_service": in_service, "in_service_end": in_service_end,
                "lat": p.lat if p.lat is not None else "",
                "lng": p.lng if p.lng is not None else "",
                "route": snapshot.format_route(p.route), "cost_usd": p.cost_usd or "",
                "approximate": p.approximate,
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


def sertp_projects(
    path: Path, areas: set[str] | None, states: list[str] | None, *, offline: bool,
) -> list[repo.NewProject]:
    entries = sertp.parse_report(path, areas=areas)
    places = PlaceCache(offline=offline, user_agent=get_settings().geocoder_user_agent)
    out = []
    stats: Counter[str] = Counter()
    try:
        for i, e in enumerate(entries, start=1):
            where = locate(e.endpoints, e.states, places, operator=e.owner,
                           bounds=sertp.AREA_BOUNDS.get(e.area))
            if states and not region.in_region(where.lat, where.lng, e.states, states):
                stats["outside --states"] += 1
                continue
            stats["review" if where.requires_review else
                  "approximate" if where.approximate else "exact"] += 1
            if i % 50 == 0:
                places.save()
                print(f"  located {i}/{len(entries)}: {dict(stats)}")
            year = date(e.year, 1, 1)
            confidence = 0.6 if where.requires_review else 0.8 if where.approximate else 0.95
            state = e.states[0] if len(e.states) == 1 else None
            out.append(repo.NewProject(
                utility=e.owner, state=state, name=title_case(e.title),
                type=ProjectType(e.kind), voltage_kv=e.voltage_kv,
                location_ref=" - ".join(title_case(n) for n in e.endpoints) +
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
    print(f"SERTP: {len(entries)} projects, {len(out)} kept; location {dict(stats)}")
    print("  by owner:", dict(Counter(p.utility for p in out).most_common()))
    return out


# ---------------------------------------------------------------- DESC / Georgia Power


def _located_project(where, **fields) -> repo.NewProject:
    confidence = 0.6 if where.requires_review else 0.8 if where.approximate else 0.95
    return repo.NewProject(
        lat=where.lat, lng=where.lng, approximate=where.approximate,
        requires_review=where.requires_review, confidence=confidence, **fields,
    )


def desc_projects(path: Path, *, offline: bool) -> list[repo.NewProject]:
    entries = desc.parse_report(path)
    places = PlaceCache(offline=offline, user_agent=get_settings().geocoder_user_agent)
    out, stats = [], Counter()
    try:
        for e in entries:
            where = locate(e.endpoints, desc.STATES, places, operator=desc.UTILITY,
                           bounds=desc.BOUNDS)
            extra = [n for n in e.description_endpoints if n not in e.endpoints]
            if where.requires_review and extra:
                # Guide Part 2: re-read the description. A new tap or substation is often
                # described by the line it hangs off ("Okatie – Riverport 230 kV"); place the
                # project on that line, approximately, and draw no route for it.
                alt = locate([*e.endpoints, *extra], desc.STATES, places,
                             operator=desc.UTILITY, bounds=desc.BOUNDS)
                if not alt.requires_review:
                    where = replace(alt, approximate=True, ends=None,
                                    how=f"{alt.how} (endpoints from the project description)")
            stats["review" if where.requires_review else
                  "approximate" if where.approximate else "exact"] += 1
            start, end = e.in_service or (None, None)
            out.append(_located_project(
                where, utility=desc.UTILITY, state="SC", name=e.title,
                type=ProjectType(e.kind), voltage_kv=e.voltage_kv,
                location_ref=" - ".join(e.endpoints),
                route=where.ends if e.kind == "transmission line" else None,
                cost_usd=e.cost_usd, start_date=start, end_date=end,
                start_precision=e.date_precision if start else None,
                end_precision=e.date_precision if end else None,
                source_url=desc.SOURCE_URL, source_page=e.page,
                raw_excerpt=f"{e.excerpt()}\n{where.how}"[:2000],
            ))
    finally:
        places.save()
    print(f"DESC: {len(entries)} projects; location {dict(stats)}")
    return out


def gpc_projects(path: Path, *, offline: bool) -> list[repo.NewProject]:
    entries = gpc_its.parse_report(path)
    places = PlaceCache(offline=offline, user_agent=get_settings().geocoder_user_agent)
    out, stats = [], Counter()
    try:
        for e in entries:
            s = e.as_sertp()
            where = locate(s.endpoints, gpc_its.STATES, places, operator=gpc_its.UTILITY,
                           bounds=gpc_its.BOUNDS)
            stats["review" if where.requires_review else
                  "approximate" if where.approximate else "exact"] += 1
            out.append(_located_project(
                where, utility=gpc_its.UTILITY, state="GA", name=title_case(s.title),
                type=ProjectType(s.kind), voltage_kv=s.voltage_kv,
                location_ref=" - ".join(title_case(n) for n in s.endpoints),
                route=where.ends if s.kind == "transmission line" else None,
                start_date=e.need, end_date=e.need, start_precision=DatePrecision.DAY,
                end_precision=DatePrecision.DAY, source_url=gpc_its.SOURCE_URL,
                source_page=e.page, raw_excerpt=f"{e.excerpt()}\n{where.how}"[:2000],
            ))
    finally:
        places.save()
    print(f"Georgia Power ITS: {len(entries)} GPC/SAV projects; location {dict(stats)}")
    return out


# ---------------------------------------------------------------- Florida


def _florida_projects(entries: list[florida.LineEntry], label: str, *,
                      offline: bool) -> list[repo.NewProject]:
    places = PlaceCache(offline=offline, user_agent=get_settings().geocoder_user_agent)
    out, stats = [], Counter()
    try:
        for e in entries:
            # Joint lines ("Duke Energy Florida / Seminole ...") locate with the first owner's
            # hints; the terminal names carry the rest.
            operator = e.owner.split(" / ")[0]
            where = locate(e.endpoints, florida.STATES, places, operator=operator,
                           bounds=florida.BOUNDS)
            stats["review" if where.requires_review else
                  "approximate" if where.approximate else "exact"] += 1
            out.append(_located_project(
                where, utility=e.owner, state="FL", name=e.title,
                type=ProjectType.TRANSMISSION_LINE, voltage_kv=e.voltage_kv,
                location_ref=" - ".join(title_case(n) for n in e.endpoints), route=where.ends,
                start_date=e.in_service, end_date=e.in_service,
                start_precision=DatePrecision.MONTH, end_precision=DatePrecision.MONTH,
                source_url=e.source_url, source_page=e.page,
                raw_excerpt=f"{e.excerpt()}\n{where.how}"[:2000],
            ))
    finally:
        places.save()
    print(f"{label}: {len(entries)} lines; location {dict(stats)}")
    print("  by owner:", dict(Counter(p.utility for p in out).most_common()))
    return out


def frcc_projects(path: Path, *, offline: bool) -> list[repo.NewProject]:
    return _florida_projects(florida.parse_frcc(path), "FRCC Form 13", offline=offline)


def tallahassee_projects(path: Path, *, offline: bool) -> list[repo.NewProject]:
    return _florida_projects(florida.parse_tallahassee(path), "City of Tallahassee",
                             offline=offline)


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
    ap.add_argument("source",
                    choices=["eia860m", "sertp", "desc", "gpc", "frcc", "tallahassee", "all"])
    ap.add_argument("--eia-file", type=Path, default=DOCS / snapshot.EIA860M.filename)
    ap.add_argument("--sertp-file", type=Path, default=DOCS / snapshot.SERTP.filename)
    ap.add_argument("--desc-file", type=Path, default=DOCS / snapshot.DESC.filename)
    ap.add_argument("--gpc-file", type=Path, default=DOCS / snapshot.GPC_ITS.filename)
    ap.add_argument("--frcc-file", type=Path, default=DOCS / snapshot.FRCC.filename)
    ap.add_argument("--tallahassee-file", type=Path,
                    default=DOCS / snapshot.TALLAHASSEE.filename)
    ap.add_argument("--states", nargs="+", default=["ALL"],
                    help="keep EIA-860M plants and SERTP projects in these states "
                         "(default: ALL; the Sperry region is SC GA FL)")
    ap.add_argument("--areas", nargs="+", help=f"SERTP areas, default all: {list(sertp.AREAS)}")
    ap.add_argument("--offline", action="store_true",
                    help="no Nominatim calls when placing SERTP/DESC/GPC projects")
    ap.add_argument("--dry-run", action="store_true", help="parse + write CSV, skip the DB")
    args = ap.parse_args()

    states = None if [s.upper() for s in args.states] == ["ALL"] else [
        s.upper() for s in args.states]
    if args.source in ("eia860m", "all"):
        projects = eia_projects(args.eia_file, states)
        out = EXTRACTED / snapshot.EIA860M.export
        write_export(out, projects, args.eia_file.name)
        if not args.dry_run:
            asyncio.run(load(snapshot.EIA860M, projects, out))

    if args.source in ("sertp", "all"):
        areas = {a.upper() for a in args.areas} if args.areas else None
        projects = sertp_projects(args.sertp_file, areas, states, offline=args.offline)
        out = EXTRACTED / snapshot.SERTP.export
        write_export(out, projects, args.sertp_file.name)
        if not args.dry_run:
            asyncio.run(load(snapshot.SERTP, projects, out))

    for name, source, build, path in (
        ("desc", snapshot.DESC, desc_projects, args.desc_file),
        ("gpc", snapshot.GPC_ITS, gpc_projects, args.gpc_file),
        ("frcc", snapshot.FRCC, frcc_projects, args.frcc_file),
        ("tallahassee", snapshot.TALLAHASSEE, tallahassee_projects, args.tallahassee_file),
    ):
        if args.source in (name, "all"):
            projects = build(path, offline=args.offline)
            out = EXTRACTED / source.export
            write_export(out, projects, path.name)
            if not args.dry_run:
                asyncio.run(load(source, projects, out))


if __name__ == "__main__":
    main()
