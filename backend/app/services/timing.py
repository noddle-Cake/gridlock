"""Build windows and how much two of them overlap. Pure functions, no I/O.

Plans mostly publish only an in-service date, often just a year. Construction leads up to
energization, so a project with no real start date is assumed to build for the
BUILD_LEAD_MONTHS before its in-service period. Timing is then scored as the share of the
two projects' combined active span that they have in common (intersection over union), so
the score reflects the projects themselves and no UI setting can inflate it.
"""

from __future__ import annotations

import calendar
from dataclasses import dataclass
from datetime import date

from app.models.enums import DatePrecision
from app.models.partial_date import PartialDate

BUILD_LEAD_MONTHS = 12


@dataclass(frozen=True)
class Window:
    start: date
    end: date  # inclusive

    @property
    def days(self) -> int:
        return (self.end - self.start).days + 1


@dataclass(frozen=True)
class TimeOverlap:
    ratio: float  # shared days / union days, 0.0-1.0
    overlap_days: int  # days both projects are building
    shared: Window | None  # the common stretch; None when the windows don't meet
    in_service_gap_days: int  # days between the two in-service dates


def period(d: date, precision: DatePrecision | None) -> Window:
    """The calendar span a stored date stands for, given the precision the source gave."""
    match precision:
        case DatePrecision.YEAR:
            pd = PartialDate(d.year)
        case DatePrecision.QUARTER:
            pd = PartialDate(d.year, quarter=(d.month - 1) // 3 + 1)
        case DatePrecision.MONTH:
            pd = PartialDate(d.year, month=d.month)
        case _:
            return Window(d, d)
    return Window(*pd.materialize())


def _months_before(d: date, months: int) -> date:
    y, m0 = divmod(d.year * 12 + d.month - 1 - months, 12)
    return date(y, m0 + 1, min(d.day, calendar.monthrange(y, m0 + 1)[1]))


def build_window(
    start: date | None, end: date | None,
    start_precision: DatePrecision | None = None, end_precision: DatePrecision | None = None,
) -> Window | None:
    """[start, in-service] when the plan gives a real range; otherwise the lead-up to the
    in-service period. None when the project has no date at all."""
    in_service_date = end or start
    if in_service_date is None:
        return None
    in_service = period(in_service_date, end_precision if end else start_precision)
    if start and end and start < end:
        return Window(period(start, start_precision).start, in_service.end)
    return Window(_months_before(in_service.start, BUILD_LEAD_MONTHS), in_service.end)


def compare(a: Window, b: Window) -> TimeOverlap:
    lo, hi = max(a.start, b.start), min(a.end, b.end)
    shared = Window(lo, hi) if lo <= hi else None
    overlap = shared.days if shared else 0
    union = a.days + b.days - overlap
    return TimeOverlap(
        ratio=overlap / union,
        overlap_days=overlap,
        shared=shared,
        in_service_gap_days=abs((a.end - b.end).days),
    )
