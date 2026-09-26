"""Dates that carry their source precision (Req 4.6).

Capital plans often say "Q2 2026" or just "2027". A PartialDate keeps exactly the
precision the source gave and materializes it to the calendar span that precision
implies, never inventing a more specific day.
"""

from __future__ import annotations

import calendar
import re
from dataclasses import dataclass
from datetime import date

from app.models.enums import DatePrecision

_MONTHS = {name.lower(): i for i, name in enumerate(calendar.month_name) if name}
_MONTHS.update({name.lower(): i for i, name in enumerate(calendar.month_abbr) if name})
_MONTHS["sept"] = 9

_YEAR = r"(?P<year>\d{4})"


@dataclass(frozen=True)
class PartialDate:
    year: int
    quarter: int | None = None
    month: int | None = None
    day: int | None = None

    def __post_init__(self) -> None:
        if not 1 <= self.year <= 9999:
            raise ValueError(f"year out of range: {self.year}")
        if self.quarter is not None and not 1 <= self.quarter <= 4:
            raise ValueError(f"quarter out of range: {self.quarter}")
        if self.month is not None:
            if not 1 <= self.month <= 12:
                raise ValueError(f"month out of range: {self.month}")
            if self.quarter is not None and self.quarter != (self.month - 1) // 3 + 1:
                raise ValueError("month is not inside the given quarter")
        if self.day is not None:
            if self.month is None:
                raise ValueError("day requires a month")
            if not 1 <= self.day <= calendar.monthrange(self.year, self.month)[1]:
                raise ValueError(f"day out of range: {self.day}")

    @property
    def precision(self) -> DatePrecision:
        if self.day is not None:
            return DatePrecision.DAY
        if self.month is not None:
            return DatePrecision.MONTH
        if self.quarter is not None:
            return DatePrecision.QUARTER
        return DatePrecision.YEAR

    def materialize(self) -> tuple[date, date]:
        """Return the inclusive [start, end] calendar span implied by the precision."""
        y = self.year
        match self.precision:
            case DatePrecision.DAY:
                d = date(y, self.month, self.day)  # type: ignore[arg-type]
                return d, d
            case DatePrecision.MONTH:
                m = self.month  # type: ignore[assignment]
                return date(y, m, 1), date(y, m, calendar.monthrange(y, m)[1])
            case DatePrecision.QUARTER:
                first = (self.quarter - 1) * 3 + 1  # type: ignore[operator]
                last = first + 2
                return date(y, first, 1), date(y, last, calendar.monthrange(y, last)[1])
            case _:
                return date(y, 1, 1), date(y, 12, 31)

    def label(self) -> str:
        match self.precision:
            case DatePrecision.DAY:
                return f"{self.year:04d}-{self.month:02d}-{self.day:02d}"
            case DatePrecision.MONTH:
                return f"{self.year:04d}-{self.month:02d}"
            case DatePrecision.QUARTER:
                return f"Q{self.quarter} {self.year}"
            case _:
                return str(self.year)

    @classmethod
    def parse(cls, value: object) -> PartialDate | None:
        """Parse common plan date spellings; returns None when undeterminable."""
        if value is None:
            return None
        if isinstance(value, date):
            return cls(value.year, month=value.month, day=value.day)
        text = str(value).strip()
        if not text:
            return None
        low = text.lower()

        patterns: list[tuple[str, str]] = [
            (rf"^{_YEAR}-(?P<month>\d{{1,2}})-(?P<day>\d{{1,2}})(?:[t ].*)?$", "ymd"),
            (rf"^(?P<month>\d{{1,2}})/(?P<day>\d{{1,2}})/{_YEAR}$", "ymd"),
            (rf"^{_YEAR}-(?P<month>\d{{1,2}})$", "ym"),
            (rf"^(?P<month>\d{{1,2}})/{_YEAR}$", "ym"),
            (rf"^q(?P<q>[1-4])[\s,/-]*(?:fy|cy)?\s*{_YEAR}$", "q"),
            (rf"^(?:fy|cy)?\s*{_YEAR}[\s,/-]*q(?P<q>[1-4])$", "q"),
            (rf"^(?P<q>[1-4])q[\s,/-]*{_YEAR}$", "q"),
            (rf"^(?:fy|cy)?\s*{_YEAR}$", "y"),
        ]
        try:
            for pattern, kind in patterns:
                m = re.match(pattern, low)
                if not m:
                    continue
                year = int(m["year"])
                if kind == "ymd":
                    return cls(year, month=int(m["month"]), day=int(m["day"]))
                if kind == "ym":
                    return cls(year, month=int(m["month"]))
                if kind == "q":
                    return cls(year, quarter=int(m["q"]))
                return cls(year)

            # "April 2026", "Apr 15, 2026", "15 April 2026"
            m = re.match(rf"^(?P<mon>[a-z]+)\.?\s+(?:(?P<day>\d{{1,2}}),?\s+)?{_YEAR}$", low)
            if m and m["mon"] in _MONTHS:
                day = int(m["day"]) if m["day"] else None
                return cls(int(m["year"]), month=_MONTHS[m["mon"]], day=day)
            m = re.match(rf"^(?P<day>\d{{1,2}})\s+(?P<mon>[a-z]+)\.?\s+{_YEAR}$", low)
            if m and m["mon"] in _MONTHS:
                return cls(int(m["year"]), month=_MONTHS[m["mon"]], day=int(m["day"]))
        except ValueError:
            return None
        return None
