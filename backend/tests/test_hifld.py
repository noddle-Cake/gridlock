"""HIFLD reference layer: owner normalization, feature parsing, paging, snapshot, /lines."""

from __future__ import annotations

import json
from datetime import date

import httpx
import pytest

from app.services import hifld
from tests.conftest import requires_db, run_db


def feature(id_: str, owner: str | None = "GEORGIA POWER CO", voltage: float = 115,
            coords=((-84.2, 30.9), (-84.1, 30.8))) -> dict:
    return {
        "type": "Feature",
        "geometry": {"type": "LineString", "coordinates": [list(c) for c in coords]},
        "properties": {
            "ID": id_, "OWNER": owner, "VOLTAGE": voltage, "VOLT_CLASS": "100-161",
            "STATUS": "IN SERVICE", "TYPE": "AC; OVERHEAD", "INFERRED": "N",
            "SUB_1": "THOMASVILLE", "SUB_2": "NOT AVAILABLE",
            "SOURCEDATE": 1409184000000, "VAL_DATE": None,
        },
    }


# ---------------------------------------------------------------- owners


@pytest.mark.parametrize(("raw", "expected"), [
    ("DUKE ENERGY FLORIDA, INC", "Duke Energy Florida"),
    ("DUKE ENERGY FLORIDA, LLC", "Duke Energy Florida"),
    ("GULF POWER CO", "Florida Power & Light"),
    ("FLORIDA POWER & LIGHT CO", "Florida Power & Light"),
    ("GEORGIA TRANSMISSION CORP", "Georgia Transmission Corp"),
    ("JEA", "JEA"),
    ("CITY OF OCALA", "City of Ocala"),
    ("TVA", "TVA"),
    ("NOT AVAILABLE", None),
    ("  ", None),
    (None, None),
])
def test_normalize_owner(raw, expected):
    assert hifld.normalize_owner(raw) == expected


# ---------------------------------------------------------------- records


def test_to_record_maps_fields_and_sentinels():
    rec = hifld.to_record(feature("7", voltage=-999999))
    assert rec is not None
    assert rec.id == "7"
    assert rec.owner == "GEORGIA POWER CO" and rec.owner_norm == "Georgia Power"
    assert rec.voltage_kv is None  # -999999 means unknown
    assert rec.sub_1 == "THOMASVILLE" and rec.sub_2 is None
    assert rec.source_date == date(2014, 8, 28) and rec.val_date is None
    assert rec.inferred is False


def test_to_record_rejects_missing_geometry_or_id():
    assert hifld.to_record({**feature("1"), "geometry": None}) is None
    no_id = feature("1")
    no_id["properties"]["ID"] = None
    assert hifld.to_record(no_id) is None


def test_records_from_dedupes_ids():
    doc = {"features": [feature("1"), feature("1", owner="JEA"), feature("2")]}
    recs = hifld.records_from(doc)
    assert [r.id for r in recs] == ["1", "2"]
    assert recs[0].owner_norm == "Georgia Power"


@pytest.mark.parametrize("bad", ["", "1,2,3", "a,b,c,d", "-80,30,-86,31", "0,95,1,96"])
def test_parse_bbox_rejects(bad):
    with pytest.raises(ValueError):
        hifld.parse_bbox(bad)


def test_parse_bbox_accepts():
    assert hifld.parse_bbox("-86,29.8,-80.8,31.6") == (-86.0, 29.8, -80.8, 31.6)


# ---------------------------------------------------------------- paging + snapshot


async def test_fetch_features_pages_until_exhausted():
    all_features = [feature(str(i)) for i in range(5)]
    offsets: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        offset = int(request.url.params["resultOffset"])
        size = int(request.url.params["resultRecordCount"])
        offsets.append(offset)
        page = all_features[offset:offset + size]
        exceeded = offset + size < len(all_features)
        return httpx.Response(200, json={
            "type": "FeatureCollection", "features": page,
            **({"properties": {"exceededTransferLimit": True}} if exceeded else {}),
        })

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        got = await hifld.fetch_features("https://example.test/0", (-86, 29, -80, 32),
                                         client=client, page_size=2)
    assert [f["properties"]["ID"] for f in got] == ["0", "1", "2", "3", "4"]
    assert offsets == [0, 2, 4]


async def test_fetch_features_surfaces_arcgis_errors(monkeypatch):
    monkeypatch.setattr(hifld.asyncio, "sleep", _no_sleep)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"error": {"code": 400, "message": "Invalid URL"}})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(RuntimeError, match="after 3 attempts"):
            await hifld.fetch_features("https://example.test/0", (-86, 29, -80, 32),
                                       client=client)


async def _no_sleep(_: float) -> None:
    return None


def test_snapshot_round_trip(tmp_path):
    path = tmp_path / "lines.geojson.gz"
    hifld.save_snapshot(path, [feature("1"), feature("2")], url="u", bbox=(-86, 29, -80, 32))
    doc = hifld.load_snapshot(path)
    assert doc["metadata"]["count"] == 2 and doc["metadata"]["bbox"] == [-86, 29, -80, 32]
    assert [r.id for r in hifld.records_from(doc)] == ["1", "2"]


def test_committed_snapshot_is_loadable():
    if not hifld.SNAPSHOT_PATH.is_file():
        pytest.skip("no committed snapshot")
    recs = hifld.records_from(hifld.load_snapshot())
    assert recs and all(r.geometry["coordinates"] for r in recs)


# ---------------------------------------------------------------- database + API


@requires_db
def test_lines_geojson_filters():
    from app.db import lines as lines_db

    recs = hifld.records_from({"features": [
        feature("a", voltage=115),
        feature("b", owner="JEA", voltage=230, coords=((-81.7, 30.4), (-81.6, 30.3))),
        feature("c", owner="NOT AVAILABLE", voltage=500, coords=((-70, 40), (-70.1, 40.1))),
    ]})

    async def body(conn):
        await lines_db.replace_lines(conn, recs)
        everything = json.loads(await lines_db.lines_geojson(conn))
        near_jax = json.loads(await lines_db.lines_geojson(conn, bbox=(-82, 30, -81, 31)))
        high = json.loads(await lines_db.lines_geojson(conn, min_kv=200))
        jea = json.loads(await lines_db.lines_geojson(conn, owners=["JEA"]))
        owners = await lines_db.line_owners(conn)
        return everything, near_jax, high, jea, owners

    everything, near_jax, high, jea, owners = run_db(body)
    assert everything["type"] == "FeatureCollection" and len(everything["features"]) == 3
    assert everything["features"][0]["geometry"]["type"] == "MultiLineString"
    assert [f["id"] for f in near_jax["features"]] == ["b"]
    assert {f["id"] for f in high["features"]} == {"b", "c"}
    assert [f["properties"]["owner_norm"] for f in jea["features"]] == ["JEA"]
    by_owner = {o.owner: o for o in owners}
    assert set(by_owner) == {"Georgia Power", "JEA", None}
    assert by_owner["JEA"].km > 0


def test_lines_route_validates_params(api_client):
    res = api_client.get("/lines", params={"bbox": "1,2,3", "min_kv": "high"})
    assert res.status_code == 422
    assert res.json()["error"]["fields"] == ["bbox", "min_kv"]


def test_lines_route_returns_geojson(api_client):
    res = api_client.get("/lines", params={"bbox": "-86,29.8,-80.8,31.6", "min_kv": "100"})
    assert res.status_code == 200
    assert res.headers["content-type"].startswith("application/geo+json")
    assert res.json()["type"] == "FeatureCollection"
    assert api_client.get("/lines/owners").status_code == 200
