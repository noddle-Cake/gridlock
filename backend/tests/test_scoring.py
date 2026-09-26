import math

from hypothesis import assume, given
from hypothesis import strategies as st

from app.models.enums import ProjectType
from app.services.scoring import (
    WEIGHTS,
    composite_score,
    distance_score,
    overlap_score,
    score_pair,
    type_similarity,
    voltage_similarity,
)

nonneg = st.floats(min_value=0, max_value=1e4, allow_nan=False)
pos = st.floats(min_value=1e-3, max_value=1e4, allow_nan=False)
unit = st.floats(min_value=0, max_value=1, allow_nan=False)
volts = st.floats(min_value=0.1, max_value=2000, allow_nan=False)
types = st.sampled_from([t.value for t in ProjectType])


def test_weights_are_convex():
    assert all(w >= 0 for w in WEIGHTS.values())
    assert math.isclose(sum(WEIGHTS.values()), 1.0)


# Feature: gridmerge, Property 3: Distance score is bounded and monotonically non-increasing
@given(nonneg, nonneg, pos)
def test_distance_score(d1, d2, radius):
    d1, d2 = sorted((d1, d2))
    s1, s2 = distance_score(d1, radius), distance_score(d2, radius)
    assert 0.0 <= s1 <= 1.0 and 0.0 <= s2 <= 1.0
    assert s1 >= s2
    assert distance_score(0.0, radius) == 1.0
    assert distance_score(radius, radius) == 0.0
    assert distance_score(radius + d1, radius) == 0.0


# Feature: gridmerge, Property 4: Overlap score is bounded and monotonically non-decreasing
@given(st.integers(-5000, 5000), st.integers(-5000, 5000), st.integers(1, 3650))
def test_overlap_score(d1, d2, max_overlap):
    d1, d2 = sorted((d1, d2))
    s1, s2 = overlap_score(d1, max_overlap), overlap_score(d2, max_overlap)
    assert 0.0 <= s1 <= 1.0 and 0.0 <= s2 <= 1.0
    assert s1 <= s2
    if d1 <= 0:
        assert s1 == 0.0
    if d2 >= max_overlap:
        assert s2 == 1.0


# Feature: gridmerge, Property 5: Type-similarity is exact and symmetric
@given(types, types)
def test_type_similarity(a, b):
    s = type_similarity(a, b)
    assert s == (1.0 if a == b else 0.0)
    assert s == type_similarity(b, a)


# Feature: gridmerge, Property 6: Voltage-similarity is bounded, monotone in difference, symmetric
@given(volts, volts, volts, volts)
def test_voltage_similarity(a, b, c, d):
    s = voltage_similarity(a, b)
    assert 0.0 <= s <= 1.0
    assert s == voltage_similarity(b, a)
    assert voltage_similarity(a, a) == 1.0
    if abs(a - b) <= abs(c - d):
        assert voltage_similarity(a, b) >= voltage_similarity(c, d)


# Feature: gridmerge, Property 7: Composite score is bounded and factor-monotone
@given(unit, unit, unit, unit, st.sampled_from(list(WEIGHTS)), unit)
def test_composite(f1, f2, f3, f4, bump, delta):
    factors = dict(zip(WEIGHTS, (f1, f2, f3, f4), strict=True))
    c = composite_score(factors)
    assert 0.0 <= c <= 1.0
    raised = dict(factors)
    raised[bump] = min(1.0, raised[bump] + delta)
    assert composite_score(raised) >= c - 1e-12


# Feature: gridmerge, Property 8: Missing factor inputs are zeroed and flagged indeterminate
@given(
    miles=st.one_of(st.none(), st.just(float("nan")), nonneg),
    overlap=st.one_of(st.none(), st.integers(-100, 1000)),
    type_a=st.one_of(st.none(), st.just(""), types),
    type_b=st.one_of(st.none(), st.just(""), types),
    va=st.one_of(st.none(), st.just(-5.0), volts),
    vb=st.one_of(st.none(), volts),
    radius=pos,
)
def test_indeterminate_factors(miles, overlap, type_a, type_b, va, vb, radius):
    s = score_pair(
        miles=miles, overlap_days=overlap, type_a=type_a, type_b=type_b,
        voltage_a=va, voltage_b=vb, radius=radius, max_overlap=365,
    )
    expect_missing = {
        "distance": miles is None or (isinstance(miles, float) and math.isnan(miles)),
        "overlap": overlap is None,
        "type_similarity": not type_a or not type_b,
        "voltage_similarity": va is None or vb is None or va <= 0 or vb <= 0,
    }
    for name, missing in expect_missing.items():
        value = getattr(s, name)
        if missing:
            assert value == 0.0
            assert name in s.indeterminate_factors
        else:
            assert name not in s.indeterminate_factors
            assert 0.0 <= value <= 1.0
    assert 0.0 <= s.composite <= 1.0


@given(nonneg, pos)
def test_score_pair_uses_distance_score(miles, radius):
    assume(miles <= radius)
    s = score_pair(miles=miles, overlap_days=10, type_a="substation", type_b="substation",
                   voltage_a=138, voltage_b=138, radius=radius, max_overlap=365)
    assert s.distance == distance_score(miles, radius)
    assert s.type_similarity == 1.0 and s.voltage_similarity == 1.0
    assert s.indeterminate_factors == []
