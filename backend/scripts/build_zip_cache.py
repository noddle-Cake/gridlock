"""Look up OpenStreetMap points for ZIP codes ahead of time, so search needn't.

    python -m scripts.build_zip_cache 33034 33157      # these ZIPs
    python -m scripts.build_zip_cache --prefix 330 331 # every Census ZCTA starting so

Writes `app/data/zip_osm_points.csv` (zip, lat, lng), which `search.locate_zip` prefers to
the Census ZCTA point. ZIPs already in the file are skipped, so a run can be resumed or
extended. One Nominatim request per ZIP at most once a second (the usage policy): a few
hundred ZIPs take minutes, so prefer a region's prefixes to the whole country. ZIPs missing
from the file are still looked up live, once per server process.

OSM data (c) OpenStreetMap contributors, ODbL. Coordinates are rounded to 4 decimals.
"""

from __future__ import annotations

import argparse
import asyncio
import csv

from app.services.search import ZIP_OSM_PATH, _zip_table, fetch_osm_zip


def read_existing() -> dict[str, tuple[float, float]]:
    if not ZIP_OSM_PATH.exists():
        return {}
    with ZIP_OSM_PATH.open(encoding="utf-8") as f:
        return {row["zip"]: (float(row["lat"]), float(row["lng"])) for row in csv.DictReader(f)}


def write(points: dict[str, tuple[float, float]]) -> None:
    with ZIP_OSM_PATH.open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f, lineterminator="\n")
        w.writerow(["zip", "lat", "lng"])
        for z in sorted(points):
            lat, lng = points[z]
            w.writerow([z, f"{lat:.4f}", f"{lng:.4f}"])


async def main(zips: list[str]) -> None:
    points = read_existing()
    todo = [z for z in zips if z not in points]
    print(f"{len(todo)} to look up ({len(zips) - len(todo)} already cached)")
    for i, z in enumerate(todo, 1):
        point = await fetch_osm_zip(z)
        if point:
            points[z] = point
        print(f"[{i}/{len(todo)}] {z}: {point or 'not in OSM'}")
        if i % 25 == 0:
            write(points)  # keep progress if interrupted
    write(points)


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("zips", nargs="*", help="five-digit ZIPs")
    ap.add_argument("--prefix", nargs="*", default=[], help="ZIP prefixes, e.g. 330 331")
    args = ap.parse_args()
    known = _zip_table()
    zips = [z for z in args.zips if z in known]
    zips += sorted(z for z in known if args.prefix and z.startswith(tuple(args.prefix)))
    if not zips:
        ap.error("no known ZIPs given")
    asyncio.run(main(list(dict.fromkeys(zips))))
