"""HIFLD transmission-line reference layer: fetch, normalize, snapshot.

These are *existing* lines (HIFLD Electric Power Transmission Lines, the dataset
behind the Felt map), not planned projects. They are a map backdrop, a roster of
which utilities operate along a border, and the real routes that planned
transmission-line projects can later be matched against (Req 17).

The public HIFLD portal was retired in 2025 and the ArcGIS service that still serves
the layer may disappear, so the fetched region is committed as a gzipped GeoJSON
snapshot and loaded from disk; the live service is only needed to refresh it.
"""

from __future__ import annotations

import asyncio
import gzip
import json
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import httpx

from app.services.owners import canonical_utility

ATTEMPT_TIMEOUT_S = 60.0
MAX_ATTEMPTS = 3
PAGE_SIZE = 1000  # the service caps a page at 2000
FIELDS = ("ID", "TYPE", "STATUS", "OWNER", "VOLTAGE", "VOLT_CLASS", "INFERRED",
          "SUB_1", "SUB_2", "SOURCEDATE", "VAL_DATE")

SNAPSHOT_PATH = Path(__file__).resolve().parent.parent / "data" / "hifld_lines.geojson.gz"

Bbox = tuple[float, float, float, float]  # min_lng, min_lat, max_lng, max_lat


def parse_bbox(value: str) -> Bbox:
    """'minLng,minLat,maxLng,maxLat' -> tuple; raises ValueError on anything else."""
    parts = [float(p) for p in value.split(",")]
    if len(parts) != 4:
        raise ValueError("bbox needs four comma-separated numbers")
    min_lng, min_lat, max_lng, max_lat = parts
    if not (-180 <= min_lng < max_lng <= 180 and -90 <= min_lat < max_lat <= 90):
        raise ValueError("bbox must be minLng,minLat,maxLng,maxLat in degrees")
    return min_lng, min_lat, max_lng, max_lat


# ---------------------------------------------------------------- owner names


def normalize_owner(raw: str | None) -> str | None:
    """Canonical owner used for grouping/colouring; None when HIFLD has no owner."""
    return canonical_utility(raw)


# ---------------------------------------------------------------- records


@dataclass(frozen=True)
class LineRecord:
    id: str
    owner: str | None
    owner_norm: str | None
    voltage_kv: float | None
    volt_class: str | None
    status: str | None
    line_type: str | None
    inferred: bool | None
    sub_1: str | None
    sub_2: str | None
    source_date: date | None
    val_date: date | None
    geometry: dict[str, Any]  # GeoJSON LineString / MultiLineString, EPSG:4326


_UNKNOWN_TEXT = {"", "NOT AVAILABLE", "UNKNOWN", "N/A", "NA"}


def _text(value: Any) -> str | None:
    if value is None:
        return None
    s = str(value).strip()
    return None if s.upper() in _UNKNOWN_TEXT else s


def _epoch_ms_date(value: Any) -> date | None:
    if not isinstance(value, int | float) or value <= 0:
        return None
    return datetime.fromtimestamp(value / 1000, tz=UTC).date()


def to_record(feature: dict[str, Any]) -> LineRecord | None:
    """One HIFLD GeoJSON feature -> LineRecord; None if it has no usable geometry."""
    geom = feature.get("geometry") or {}
    if geom.get("type") not in ("LineString", "MultiLineString") or not geom.get("coordinates"):
        return None
    p = feature.get("properties") or {}
    if p.get("ID") in (None, ""):
        return None
    voltage = p.get("VOLTAGE")
    raw_owner = p.get("OWNER")
    inferred = p.get("INFERRED")
    return LineRecord(
        id=str(p["ID"]),
        owner=_text(raw_owner),
        owner_norm=normalize_owner(raw_owner),
        # HIFLD uses -999999 for "unknown voltage".
        voltage_kv=float(voltage) if isinstance(voltage, int | float) and voltage > 0 else None,
        volt_class=_text(p.get("VOLT_CLASS")),
        status=_text(p.get("STATUS")),
        line_type=_text(p.get("TYPE")),
        inferred={"Y": True, "N": False}.get(str(inferred).upper()) if inferred else None,
        sub_1=_text(p.get("SUB_1")),
        sub_2=_text(p.get("SUB_2")),
        source_date=_epoch_ms_date(p.get("SOURCEDATE")),
        val_date=_epoch_ms_date(p.get("VAL_DATE")),
        geometry=geom,
    )


# ---------------------------------------------------------------- live service


async def fetch_features(
    url: str, bbox: Bbox, *, client: httpx.AsyncClient | None = None,
    page_size: int = PAGE_SIZE,
) -> list[dict[str, Any]]:
    """Every HIFLD feature intersecting `bbox`, paging until the service is exhausted."""
    owns_client = client is None
    client = client or httpx.AsyncClient(timeout=ATTEMPT_TIMEOUT_S)
    features: list[dict[str, Any]] = []
    try:
        offset = 0
        while True:
            page = await _fetch_page(client, url, bbox, offset, page_size)
            batch = page.get("features") or []
            features.extend(batch)
            exceeded = (page.get("properties") or {}).get("exceededTransferLimit", False)
            if not batch or (not exceeded and len(batch) < page_size):
                return features
            offset += len(batch)
    finally:
        if owns_client:
            await client.aclose()


async def _fetch_page(
    client: httpx.AsyncClient, url: str, bbox: Bbox, offset: int, page_size: int
) -> dict[str, Any]:
    params = {
        "where": "1=1",
        "geometry": ",".join(str(v) for v in bbox),
        "geometryType": "esriGeometryEnvelope",
        "inSR": "4326",
        "spatialRel": "esriSpatialRelIntersects",
        "outFields": ",".join(FIELDS),
        "outSR": "4326",
        "geometryPrecision": "5",  # ~1 m; keeps the snapshot small
        "orderByFields": "OBJECTID_1",
        "resultOffset": str(offset),
        "resultRecordCount": str(page_size),
        "f": "geojson",
    }
    last_error: Exception | None = None
    for attempt in range(MAX_ATTEMPTS):
        try:
            resp = await client.get(f"{url.rstrip('/')}/query", params=params)
            resp.raise_for_status()
            body = resp.json()
            if "error" in body:  # ArcGIS reports errors with HTTP 200
                raise RuntimeError(f"HIFLD service error: {body['error']}")
            return body
        except (httpx.HTTPError, ValueError, RuntimeError) as exc:
            last_error = exc
            if attempt + 1 < MAX_ATTEMPTS:
                await asyncio.sleep(2**attempt)
    raise RuntimeError(f"HIFLD query failed after {MAX_ATTEMPTS} attempts: {last_error}")


# ---------------------------------------------------------------- snapshot


def save_snapshot(path: Path, features: list[dict[str, Any]], *, url: str, bbox: Bbox) -> None:
    doc = {
        "type": "FeatureCollection",
        "metadata": {
            "source": "HIFLD Electric Power Transmission Lines",
            "url": url,
            "bbox": list(bbox),
            "fetched_at": datetime.now(UTC).isoformat(timespec="seconds"),
            "count": len(features),
        },
        "features": features,
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    # mtime=0 so the gzip header alone never makes a refresh show up as a diff.
    with gzip.GzipFile(path, "wb", mtime=0) as f:
        f.write(json.dumps(doc, separators=(",", ":"), sort_keys=True).encode("utf-8"))


def load_snapshot(path: Path = SNAPSHOT_PATH) -> dict[str, Any]:
    with gzip.open(path, "rb") as f:
        return json.loads(f.read().decode("utf-8"))


def records_from(doc: dict[str, Any]) -> list[LineRecord]:
    """Records from a FeatureCollection, keeping the first copy of any duplicate ID."""
    seen: set[str] = set()
    out: list[LineRecord] = []
    for feature in doc.get("features") or []:
        rec = to_record(feature)
        if rec and rec.id not in seen:
            seen.add(rec.id)
            out.append(rec)
    return out
