"""Audit live rows read-only, or committed snapshots in a rolled-back temporary schema.

python -m scripts.audit_collisions --snapshots --as-of 2026-09-27
python -m scripts.audit_collisions --live --as-of 2026-09-27

Snapshots use TEST_DATABASE_URL (a disposable PostGIS database); live uses DATABASE_URL.
No production writes, credentials, or raw source excerpts are included in the report.
"""

import argparse
import asyncio
import json
import os
import uuid
from collections import Counter
from datetime import date

import asyncpg

from app.core.config import get_settings
from app.db import repository as repo
from app.db.pool import SCHEMA_PATH
from app.services import matching
from app.services.owners import corporate_entities, ownership_review_required
from app.sources import snapshot


async def audit(args):
    url = (os.environ.get("TEST_DATABASE_URL",
                          "postgresql://gridmerge:gridmerge@127.0.0.1:5433/gridmerge_test")
           if args.snapshots else get_settings().database_url)
    conn = await asyncpg.connect(url, timeout=10)
    transaction = conn.transaction(readonly=not args.snapshots, isolation="repeatable_read")
    await transaction.start()
    try:
        if args.snapshots:
            schema = "audit_" + uuid.uuid4().hex
            await conn.execute(f'CREATE SCHEMA "{schema}"')
            await conn.execute(f'SET LOCAL search_path TO "{schema}", public')
            await conn.execute(SCHEMA_PATH.read_text())
            for source in snapshot.SOURCES:
                await snapshot.save(conn, source,
                                    snapshot.read_export(snapshot.EXTRACTED_DIR / source.export))
        projects = await repo.list_projects(conn)
        current = [p for p in projects if not matching.is_past(p, args.as_of)]
        pairs = await matching.overlaps(conn, 40 / matching.KM_PER_MILE,
                                       rules=matching.Rules(args.as_of, 30))
        all_counts = Counter(p.utility for p in projects)
        current_counts = Counter(p.utility for p in current)
        return {
            "scope": "committed snapshots" if args.snapshots else "live database (read-only)",
            "as_of": args.as_of.isoformat(), "radius_km": 40, "min_remaining_overlap_days": 30,
            "total_projects": len(projects), "current_projects": len(current),
            "archived_projects": len(projects) - len(current), "matches": len(pairs),
            "companies": [{"utility": u, "total": n, "current": current_counts[u],
                           "ownership_review_required": ownership_review_required(u),
                           "corporate_groups": sorted(corporate_entities(u))
                           if not ownership_review_required(u) else []}
                          for u, n in sorted(all_counts.items())],
            "sources": [{"url": url, "projects": n}
                        for url, n in Counter(p.source_url for p in projects).items()],
            "pairs": [{"companies": [p.project_a.utility, p.project_b.utility],
                       "projects": [p.project_a.name, p.project_b.name],
                       "sources": [p.project_a.source_url, p.project_b.source_url],
                       "pages": [p.project_a.source_page, p.project_b.source_page],
                       "km": round(p.miles * matching.KM_PER_MILE, 2),
                       "remaining_start": max(p.window_start, args.as_of).isoformat(),
                       "remaining_end": p.window_end.isoformat(),
                       "approximate_location": p.project_a.approximate or p.project_b.approximate}
                      for p in pairs],
        }
    finally:
        await transaction.rollback()
        await conn.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--snapshots", action="store_true")
    mode.add_argument("--live", action="store_true")
    parser.add_argument("--as-of", type=date.fromisoformat, default=date.today())
    args = parser.parse_args()
    print(json.dumps(asyncio.run(audit(args)), indent=2))


if __name__ == "__main__":
    main()
