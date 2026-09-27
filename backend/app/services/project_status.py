"""Dated operating evidence that supersedes an older planned-source snapshot.

Exact source/name keys prevent a completed plant from hiding unrelated expansions.
The original planned dates remain intact; as_of is an upper bound, not a guessed COD.
"""

from dataclasses import dataclass
from datetime import date


@dataclass(frozen=True)
class OperatingEvidence:
    plan_url: str
    name: str
    as_of: date
    source_url: str


OPERATING_EVIDENCE = (
    OperatingEvidence(
        "https://www.eia.gov/electricity/data/eia860m/xls/august_generator2026.xlsx",
        "Kingstree West 115 (Solar Photovoltaic, 74.9 MW)",
        date(2026, 9, 23),
        "https://www.ikea.com/us/en/newsroom/corporate-news/"
        "ingka-investments-brings-kingstree-west-solar-farm-into-operation-adding-new-"
        "renewable-electricity-in-south-carolina-pub9c17e940/",
    ),
)


def operating_evidence(source_url: str | None, name: str | None) -> OperatingEvidence | None:
    return next((e for e in OPERATING_EVIDENCE if (e.plan_url, e.name) == (source_url, name)), None)
