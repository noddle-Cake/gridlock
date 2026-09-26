import calendar
from datetime import date

from hypothesis import given
from hypothesis import strategies as st

from app.models.enums import DatePrecision
from app.models.partial_date import PartialDate


@st.composite
def partial_dates(draw):
    year = draw(st.integers(1900, 2100))
    precision = draw(st.sampled_from(list(DatePrecision)))
    if precision is DatePrecision.YEAR:
        return PartialDate(year)
    if precision is DatePrecision.QUARTER:
        return PartialDate(year, quarter=draw(st.integers(1, 4)))
    month = draw(st.integers(1, 12))
    if precision is DatePrecision.MONTH:
        return PartialDate(year, month=month)
    day = draw(st.integers(1, calendar.monthrange(year, month)[1]))
    return PartialDate(year, month=month, day=day)


def _spellings(p: PartialDate) -> list[str]:
    y = p.year
    match p.precision:
        case DatePrecision.YEAR:
            return [str(y), f"FY{y}"]
        case DatePrecision.QUARTER:
            return [f"Q{p.quarter} {y}", f"{y}-Q{p.quarter}", f"{p.quarter}Q{y}"]
        case DatePrecision.MONTH:
            return [f"{y}-{p.month:02d}", f"{calendar.month_name[p.month]} {y}"]
        case _:
            return [f"{y}-{p.month:02d}-{p.day:02d}", f"{p.month}/{p.day}/{y}"]


# Feature: gridlock, Property 10: Date precision is preserved, never refined
@given(partial_dates(), st.data())
def test_precision_preserved_and_span_canonical(p: PartialDate, data):
    spelling = data.draw(st.sampled_from(_spellings(p)))
    parsed = PartialDate.parse(spelling)
    assert parsed is not None
    assert parsed.precision == p.precision  # never finer, never coarser
    assert parsed == p

    start, end = parsed.materialize()
    y = p.year
    match p.precision:
        case DatePrecision.YEAR:
            assert (start, end) == (date(y, 1, 1), date(y, 12, 31))
        case DatePrecision.QUARTER:
            first = 3 * (p.quarter - 1) + 1
            assert start == date(y, first, 1)
            assert end == date(y, first + 2, calendar.monthrange(y, first + 2)[1])
        case DatePrecision.MONTH:
            assert start == date(y, p.month, 1)
            assert end == date(y, p.month, calendar.monthrange(y, p.month)[1])
        case DatePrecision.DAY:
            assert start == end == date(y, p.month, p.day)


def test_q2_example():
    assert PartialDate.parse("Q2 2026").materialize() == (date(2026, 4, 1), date(2026, 6, 30))


def test_unparseable_is_empty():
    assert PartialDate.parse("") is None
    assert PartialDate.parse("TBD") is None
    assert PartialDate.parse("2026-02-30") is None
