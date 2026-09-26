"""Committed snapshots of the public-source loads, loaded at startup when missing.

`scripts.load_public_sources` writes one citation CSV per source to
`source_docs/extracted/`. Those CSVs hold everything a project row needs, so a deployed
instance (AWS Lightsail) gets the same records without the raw PDFs/XLSX, network
lookups or an LLM: on startup each source whose plan isn't in the database yet is
inserted from its CSV. Re-running the loader script replaces the same plan.
"""

from __future__ import annotations

import csv
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


async def save(conn: asyncpg.Connection, source: Source, projects: list[repo.NewProject]) -> str:
    return await replace_source(
        conn, label=source.label, source_url=source.source_url, filename=source.filename,
        detected_format=source.detected_format, projects=projects,
        page_range=page_range(projects) if source.detected_format == "pdf" else None,
    )


async def load_snapshots_if_missing(pool: asyncpg.Pool, directory: Path = EXTRACTED_DIR) -> None:
    async with pool.acquire() as conn:
        for source in SOURCES:
            path = directory / source.export
            if not path.exists():
                log.warning("public-source snapshot missing: %s", path)
                continue
            loaded = await conn.fetchval(
                "SELECT 1 FROM plans WHERE source_url = $1 AND filename = $2",
                source.source_url, source.filename + LOADER_SUFFIX,
            )
            if loaded:
                continue
            projects = read_export(path)
            await save(conn, source, projects)
            log.info("loaded %d projects from %s", len(projects), path.name)
