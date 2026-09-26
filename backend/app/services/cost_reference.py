"""Historical project costs for pricing (app/data/reference_costs.csv).

The file ships empty: add rows from your own cost history or public filings (e.g. RTO
project lists with in-service costs). One row per project:

    name,utility,state,scope,voltage_kv,size,cost_musd,cost_year,actual,source_url

`scope` is a CostScope value (new_line, line_rebuild, reconductor, breaker, ...); `size` is
line miles for per-mile scopes and a unit count otherwise; `cost_musd` is in `cost_year`
dollars; `actual` is true for completed-project actuals, false for estimates. Rows that
don't parse are skipped and logged.
"""

from __future__ import annotations

import csv
import logging
from functools import lru_cache
from pathlib import Path

from app.models.enums import CostScope
from app.services.pricing import CostRecord

log = logging.getLogger(__name__)

REFERENCE_PATH = Path(__file__).resolve().parents[1] / "data" / "reference_costs.csv"


def parse_rows(rows: list[dict[str, str]]) -> list[CostRecord]:
    records = []
    for n, row in enumerate(rows, start=2):
        try:
            records.append(CostRecord(
                scope=CostScope(row["scope"].strip()),
                voltage_kv=float(row["voltage_kv"]),
                size=float(row.get("size") or 1),
                cost_musd=float(row["cost_musd"]),
                cost_year=int(row["cost_year"]),
                utility=(row.get("utility") or "").strip(),
                state=(row.get("state") or "").strip(),
                name=(row.get("name") or "").strip(),
                actual=(row.get("actual") or "").strip().lower() in ("1", "true", "yes"),
                source=(row.get("source_url") or "reference_costs.csv").strip(),
            ))
        except (KeyError, ValueError, AttributeError) as exc:
            log.warning("reference_costs.csv line %d skipped: %s", n, exc)
    return [r for r in records if r.cost_musd > 0 and r.size > 0 and r.voltage_kv > 0]


@lru_cache
def reference_records(path: Path = REFERENCE_PATH) -> tuple[CostRecord, ...]:
    if not path.exists():
        return ()
    with path.open(newline="", encoding="utf-8") as fh:
        return tuple(parse_rows(list(csv.DictReader(fh))))
