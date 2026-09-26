"""Committed snapshots of the public-source loads, loaded at startup when missing.

`scripts.load_public_sources` writes one citation CSV per source to
`source_docs/extracted/`. Those CSVs hold everything a project row needs, so a deployed
instance (AWS Lightsail) gets the same records without the raw PDFs/XLSX, network
lookups or an LLM: on startup each source whose plan is missing, or was loaded from a
different version of its CSV (tracked by SHA-256), is (re)inserted from the CSV.
Re-running the loader script replaces the same plan.
"""

from __future__ import annotations

import csv
import hashlib
import logging
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import asyncpg

from app.db import repository as repo
from app.models.enums import DatePrecision, ProjectType
from app.sources import eia860m, sertp
from app.sources.store import LOADER_SUFFIX, replace_source

log = logging.getLogger(__name__)

# Repo: <root>/source_docs/extracted; image: /srv/source_docs/extracted (Dockerfile).
EXTRACTED_DIR = Path(__file__).resolve().parents[3] / "source_docs" / "extracted"


@dataclass(frozen=True)
class Source:
    label: str
    source_url: str
    filename: str  # the raw file in source_docs/
    detected_format: str
    export: str  # CSV in source_docs/extracted/


EIA860M = Source(
    "EIA-860M planned generators (Aug 2026)", eia860m.SOURCE_URL,
    "eia860m_august_generator2026.xlsx", "xlsx", "eia860m_planned_generators.csv",
)
SERTP = Source(
    "SERTP 2026 preliminary expansion plan", sertp.SOURCE_URL,
    "sertp_2026_preliminary_expansion_plan.pdf", "pdf", "sertp_2026_preliminary_projects.csv",
)
SOURCES = [EIA860M, SERTP]


def _bool(value: str) -> bool:
    return value.strip().lower() == "true"


def _float(value: str) -> float | None:
    return float(value) if value.strip() else None


def parse_route(value: str | None) -> list[tuple[float, float]] | None:
    """'33.56 -82.05;33.66 -82.19' -> [(33.56, -82.05), (33.66, -82.19)]."""
    if not value or not value.strip():
        return None
    points = [tuple(float(x) for x in part.split()) for part in value.split(";")]
    return [(lat, lng) for lat, lng in points] if len(points) >= 2 else None


def format_route(route: list[tuple[float, float]] | None) -> str:
    return ";".join(f"{lat} {lng}" for lat, lng in route) if route else ""


def read_export(path: Path) -> list[repo.NewProject]:
    """A citation CSV written by `load_public_sources.write_export` -> project rows."""
    projects = []
    with path.open(encoding="utf-8", newline="") as f:
        for row in csv.DictReader(f):
            year, _, month = row["in_service"].partition("-")
            precision = DatePrecision.MONTH if month else DatePrecision.YEAR
            when = date(int(year), int(month or 1), 1)
            projects.append(repo.NewProject(
                utility=row["utility"], state=row["state"] or None, name=row["name"],
                type=ProjectType(row["type"]) if row["type"] else None,
                voltage_kv=_float(row["voltage_kv"]), location_ref=row["location_ref"],
                lat=_float(row["lat"]), lng=_float(row["lng"]),
                route=parse_route(row.get("route")),
                start_date=when, end_date=when, start_precision=precision,
                end_precision=precision, confidence=float(row["confidence"]),
                source_url=row["source_url"], source_page=int(row["source_page"]),
                raw_excerpt=row["raw_excerpt"], approximate=_bool(row["approximate"]),
                requires_review=_bool(row["requires_review"]),
            ))
    return projects


def page_range(projects: list[repo.NewProject]) -> str | None:
    """Pages a load covers, e.g. '1-115' or '2'."""
    pages = sorted({p.source_page for p in projects if p.source_page})
    if not pages:
        return None
    runs, start, prev = [], pages[0], pages[0]
    for n in pages[1:]:
        if n != prev + 1:
            runs.append(f"{start}-{prev}" if prev > start else str(start))
            start = n
        prev = n
    runs.append(f"{start}-{prev}" if prev > start else str(start))
    return ",".join(runs)


def file_sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


async def save(
    conn: asyncpg.Connection, source: Source, projects: list[repo.NewProject],
    snapshot_sha: str | None = None,
) -> str:
    return await replace_source(
        conn, label=source.label, source_url=source.source_url, filename=source.filename,
        detected_format=source.detected_format, projects=projects,
        page_range=page_range(projects) if source.detected_format == "pdf" else None,
        snapshot_sha=snapshot_sha,
    )


async def load_snapshots(pool: asyncpg.Pool, directory: Path = EXTRACTED_DIR) -> None:
    """Insert each source whose plan is missing, or whose committed CSV changed since it
    was loaded (e.g. the EIA-860M scope went from the Southeast to nationwide). A reload
    replaces that source's projects; briefs on them are dropped with them."""
    async with pool.acquire() as conn:
        for source in SOURCES:
            path = directory / source.export
            if not path.exists():
                log.warning("public-source snapshot missing: %s", path)
                continue
            sha = file_sha(path)
            loaded = await conn.fetchval(
                "SELECT snapshot_sha FROM plans WHERE source_url = $1 AND filename = $2",
                source.source_url, source.filename + LOADER_SUFFIX,
            )
            if loaded == sha:
                continue
            projects = read_export(path)
            await save(conn, source, projects, sha)
            log.info("loaded %d projects from %s", len(projects), path.name)
