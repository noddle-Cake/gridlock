"""Build the offline OpenStreetMap substation gazetteer used to place SERTP projects.

    python -m scripts.build_substation_cache            # SERTP + Florida states
    python -m scripts.build_substation_cache --states GA AL

Transmission plans name substations, not coordinates. This queries the Overpass API once
per state for every named `power=substation` / `power=plant` feature and writes
`app/data/osm_substations.csv` (state, name, power, operator, lat, lng). The geocoder only
reads that file, so the lookup happens once and is cached in the repo.

OSM data (c) OpenStreetMap contributors, ODbL. Everything here is already public on the
OSM map; coordinates are rounded to 3 decimals (~100 m).
"""

from __future__ import annotations

import argparse
import csv
import time
from pathlib import Path

import httpx

from app.core.config import get_settings

OUT_PATH = Path(__file__).resolve().parents[1] / "app" / "data" / "osm_substations.csv"
OVERPASS_URL = "https://overpass-api.de/api/interpreter"
# SERTP footprint (Southern, TVA, Duke, LG&E/KU, AECI, PowerSouth, ...) plus Florida.
DEFAULT_STATES = ["AL", "GA", "MS", "FL", "TN", "KY", "NC", "SC", "VA", "MO", "AR", "OK"]

QUERY = """[out:json][timeout:240];
area["ISO3166-2"="US-{state}"][admin_level=4]->.a;
nwr["power"~"^(substation|plant)$"]["name"](area.a);
out center tags;"""


def fetch_state(client: httpx.Client, state: str) -> list[dict]:
    for attempt in range(3):
        resp = client.post(OVERPASS_URL, data={"data": QUERY.format(state=state)})
        if resp.status_code == 200:
            break
        time.sleep(30 * (attempt + 1))  # 429/504: Overpass asks clients to back off
    resp.raise_for_status()
    rows = []
    for el in resp.json()["elements"]:
        tags = el.get("tags", {})
        lat = el.get("lat", el.get("center", {}).get("lat"))
        lng = el.get("lon", el.get("center", {}).get("lon"))
        if lat is None or lng is None or not tags.get("name"):
            continue
        rows.append({
            "state": state, "name": tags["name"].strip(), "power": tags.get("power", ""),
            "operator": tags.get("operator", ""), "lat": round(lat, 3), "lng": round(lng, 3),
        })
    return rows


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--states", nargs="+", default=DEFAULT_STATES)
    args = ap.parse_args()

    headers = {"User-Agent": get_settings().geocoder_user_agent}
    rows: list[dict] = []
    with httpx.Client(headers=headers, timeout=300) as client:
        for state in args.states:
            got = fetch_state(client, state)
            print(f"{state}: {len(got)} named substations/plants")
            rows += got
            time.sleep(5)

    rows.sort(key=lambda r: (r["state"], r["name"].lower(), r["lat"], r["lng"]))
    with OUT_PATH.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["state", "name", "power", "operator", "lat", "lng"])
        w.writeheader()
        w.writerows(rows)
    print(f"wrote {len(rows)} rows -> {OUT_PATH}")


if __name__ == "__main__":
    main()
