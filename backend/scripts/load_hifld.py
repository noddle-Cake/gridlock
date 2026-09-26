"""Load (and optionally refresh) the HIFLD transmission-line reference layer.

    python -m scripts.load_hifld                  # committed snapshot -> DATABASE_URL
    python -m scripts.load_hifld --fetch          # refresh snapshot from HIFLD, then load
    python -m scripts.load_hifld --fetch --no-load --bbox=-86,29.8,-80.8,31.6

The app also loads the snapshot on startup when the table is empty, so this is only
needed to refresh the data, change the region, or reload after editing hifld.py.
Pass --bbox with `=` so a negative longitude is not read as a flag.
"""

from __future__ import annotations

import argparse
import asyncio
from collections import Counter
from pathlib import Path

from app.core.config import get_settings
from app.db import lines as lines_db
from app.db.pool import apply_schema, create_pool
from app.services import hifld


async def run(*, fetch: bool, load: bool, bbox: hifld.Bbox, snapshot: Path) -> None:
    settings = get_settings()
    if fetch:
        print(f"fetching HIFLD lines in {bbox} from {settings.hifld_lines_url}")
        features = await hifld.fetch_features(settings.hifld_lines_url, bbox)
        hifld.save_snapshot(snapshot, features, url=settings.hifld_lines_url, bbox=bbox)
        print(f"wrote {len(features)} features to {snapshot}")

    doc = hifld.load_snapshot(snapshot)
    records = hifld.records_from(doc)
    meta = doc.get("metadata", {})
    print(f"snapshot: {len(records)} lines, fetched {meta.get('fetched_at', '?')}")
    owners = Counter(r.owner_norm or "(owner not published)" for r in records)
    for name, n in owners.most_common():
        print(f"  {n:5d}  {name}")

    if load:
        pool = await create_pool(settings.database_url)
        try:
            await apply_schema(pool)
            async with pool.acquire() as conn:
                n = await lines_db.replace_lines(conn, records)
            print(f"loaded {n} lines into the database")
        finally:
            await pool.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--fetch", action="store_true", help="refresh the snapshot from HIFLD")
    parser.add_argument("--no-load", action="store_true", help="do not write to the database")
    parser.add_argument("--bbox", default=get_settings().hifld_bbox,
                        help="minLng,minLat,maxLng,maxLat (default: HIFLD_BBOX)")
    parser.add_argument("--snapshot", type=Path, default=hifld.SNAPSHOT_PATH)
    args = parser.parse_args()
    try:
        bbox = hifld.parse_bbox(args.bbox)
    except ValueError as exc:
        parser.error(f"--bbox: {exc}")
    asyncio.run(run(fetch=args.fetch, load=not args.no_load, bbox=bbox,
                    snapshot=args.snapshot))


if __name__ == "__main__":
    main()
