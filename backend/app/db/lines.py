"""Data access for the HIFLD transmission-line reference layer (existing lines)."""

from __future__ import annotations

import json
import logging
from pathlib import Path

import asyncpg

from app.models.dto import LineOwnerDTO
from app.services import hifld

log = logging.getLogger(__name__)

# ~0.0002 degrees is ~20 m: invisible at map zooms, roughly halves the payload.
DEFAULT_SIMPLIFY_DEG = 0.0002


async def replace_lines(conn: asyncpg.Connection, records: list[hifld.LineRecord]) -> int:
    """Swap the whole reference layer for `records` in one transaction."""
    async with conn.transaction():
        await conn.execute("TRUNCATE transmission_lines")
        await conn.executemany(
            """INSERT INTO transmission_lines (
                 id, owner, owner_norm, voltage_kv, volt_class, status, line_type, inferred,
                 sub_1, sub_2, source_date, val_date, geom)
               VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12,
                 ST_Multi(ST_SetSRID(ST_GeomFromGeoJSON($13), 4326))::geography)""",
            [
                (r.id, r.owner, r.owner_norm, r.voltage_kv, r.volt_class, r.status, r.line_type,
                 r.inferred, r.sub_1, r.sub_2, r.source_date, r.val_date, json.dumps(r.geometry))
                for r in records
            ],
        )
    return len(records)


async def count_lines(conn: asyncpg.Connection) -> int:
    return await conn.fetchval("SELECT count(*) FROM transmission_lines")


async def load_snapshot_if_empty(pool: asyncpg.Pool, path: Path = hifld.SNAPSHOT_PATH) -> int:
    """Startup hook: seed the layer from the committed snapshot on a fresh database."""
    if not path.is_file():
        return 0
    async with pool.acquire() as conn:
        if await count_lines(conn):
            return 0
        n = await replace_lines(conn, hifld.records_from(hifld.load_snapshot(path)))
    log.info("loaded %d HIFLD transmission lines from %s", n, path.name)
    return n


async def lines_geojson(
    conn: asyncpg.Connection,
    *,
    bbox: hifld.Bbox | None = None,
    min_kv: float | None = None,
    owners: list[str] | None = None,
    simplify_deg: float = DEFAULT_SIMPLIFY_DEG,
) -> str:
    """A GeoJSON FeatureCollection string, built in Postgres to avoid a JSON round trip."""
    min_lng, min_lat, max_lng, max_lat = bbox or (None, None, None, None)
    return await conn.fetchval(
        """SELECT json_build_object(
             'type', 'FeatureCollection',
             'features', coalesce(json_agg(json_build_object(
               'type', 'Feature',
               'id', id,
               -- ST_Multi: simplify returns single parts as LineString; the client
               -- relies on MultiLineString.
               'geometry', ST_AsGeoJSON(
                   ST_Multi(ST_SimplifyPreserveTopology(geom::geometry, $6)), 5)::json,
               'properties', json_build_object(
                 'owner', owner, 'owner_norm', owner_norm, 'voltage_kv', voltage_kv,
                 'volt_class', volt_class, 'status', status, 'sub_1', sub_1, 'sub_2', sub_2)
             ) ORDER BY voltage_kv NULLS FIRST, id), '[]'::json)
           )::text
           FROM transmission_lines
           WHERE ($1::float8 IS NULL
                  OR geom && ST_MakeEnvelope($1, $2, $3, $4, 4326)::geography)
             AND ($5::float8 IS NULL OR voltage_kv >= $5)
             AND ($7::text[] IS NULL OR owner_norm = ANY($7))""",
        min_lng, min_lat, max_lng, max_lat, min_kv, simplify_deg, owners,
    )


async def line_owners(conn: asyncpg.Connection) -> list[LineOwnerDTO]:
    rows = await conn.fetch(
        """SELECT owner_norm, count(*) AS line_count,
                  sum(ST_Length(geom)) / 1000 AS km,
                  min(voltage_kv) AS min_kv, max(voltage_kv) AS max_kv,
                  array_agg(DISTINCT owner) FILTER (WHERE owner IS NOT NULL) AS raw_names
           FROM transmission_lines
           GROUP BY owner_norm
           ORDER BY count(*) DESC, owner_norm NULLS LAST"""
    )
    return [
        LineOwnerDTO(
            owner=r["owner_norm"], line_count=r["line_count"], km=round(r["km"] or 0, 1),
            min_kv=r["min_kv"], max_kv=r["max_kv"], raw_names=sorted(r["raw_names"] or []),
        )
        for r in rows
    ]
