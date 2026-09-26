"""Build windows and their overlap ratio (services/timing.py)."""

from __future__ import annotations

from datetime import date

import pytest
from hypothesis import given
from hypothesis import strategies as st

from app.models.enums import DatePrecision as P
from app.services.timing import Window, build_window, compare


def test_real_range_is_used_as_is():
    w = build_window(date(2026, 4, 1), date(2026, 9, 30))
    assert w == Window(date(2026, 4, 1), date(2026, 9, 30))


def test_real_range_expands_to_its_precision():
    w = build_window(date(2026, 4, 1), date(2026, 10, 1), P.QUARTER, P.QUARTER)
    assert w == Window(date(2026, 4, 1), date(2026, 12, 31))


@pytest.mark.parametrize(
    ("in_service", "precision", "expected"),
    [
        (date(2026, 1, 1), P.YEAR, Window(date(2025, 1, 1), date(2026, 12, 31))),
        (date(2026, 4, 1), P.QUARTER, Window(date(2025, 4, 1), date(2026, 6, 30))),
        (date(2026, 6, 1), P.MONTH, Window(date(2025, 6, 1), date(2026, 6, 30))),
        (date(2026, 6, 15), P.DAY, Window(date(2025, 6, 15), date(2026, 6, 15))),
        (date(2024, 2, 29), None, Window(date(2023, 2, 28), date(2024, 2, 29))),
    ],
)
def test_in_service_only_builds_for_the_year_before(in_service, precision, expected):
    assert build_window(in_service, in_service, precision, precision) == expected
    assert build_window(None, in_service, None, precision) == expected
    assert build_window(in_service, None, precision, None) == expected


def test_undated_has_no_window():
    assert build_window(None, None) is None


def test_same_in_service_year_is_full_overlap():
    """The old ±pad math scored this 61 days / 0.17; the projects are identical in time."""
    a = build_window(date(2026, 1, 1), date(2026, 1, 1), P.YEAR, P.YEAR)
    b = build_window(None, date(2026, 1, 1), None, P.YEAR)
    t = compare(a, b)
    assert t.ratio == 1.0 and t.in_service_gap_days == 0
    assert t.shared == a


def test_disjoint_windows():
    t = compare(Window(date(2024, 1, 1), date(2024, 12, 31)),
                Window(date(2026, 1, 1), date(2026, 6, 30)))
    assert t.ratio == 0 and t.overlap_days == 0 and t.shared is None
    assert t.in_service_gap_days == (date(2026, 6, 30) - date(2024, 12, 31)).days


def test_short_job_inside_long_job_is_intersection_over_union():
    long, short = Window(date(2025, 1, 1), date(2026, 12, 31)), Window(date(2025, 4, 1),
                                                                        date(2025, 6, 30))
    t = compare(long, short)
    assert t.overlap_days == short.days
    assert t.ratio == pytest.approx(short.days / long.days)


def test_spec_example_jasper_okatie_vs_mcintosh():
    """Projects_Overlaps.xlsx OVL_2: in service 12/31/2025 and 6/1/2026, 152 days apart."""
    desc = build_window(None, date(2025, 12, 31), None, P.DAY)
    gpc = build_window(None, date(2026, 6, 1), None, P.DAY)
    t = compare(desc, gpc)
    assert t.in_service_gap_days == 152
    assert t.shared == Window(date(2025, 6, 1), date(2025, 12, 31))
    assert t.ratio == pytest.approx(214 / (366 + 366 - 214))


dates = st.dates(date(2000, 1, 1), date(2060, 12, 31))
windows = st.tuples(dates, dates).map(lambda d: Window(min(d), max(d)))


@given(windows, windows)
def test_ratio_is_symmetric_and_bounded(a, b):
    ab, ba = compare(a, b), compare(b, a)
    assert ab == ba
    assert 0.0 <= ab.ratio <= 1.0
    assert (ab.ratio == 1.0) == (a == b)
    assert (ab.shared is None) == (ab.ratio == 0.0)
