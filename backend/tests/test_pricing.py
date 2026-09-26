import math
from datetime import date

import pytest
from hypothesis import given
from hypothesis import strategies as st

from app.models.dto import AllocationRequest, ProjectDTO
from app.models.enums import CostScope, ProjectType
from app.services import cost_reference, pricing
from app.services.pricing import CostRecord

YEAR = 2026
SUB, LINE, GEN = ProjectType.SUBSTATION, ProjectType.TRANSMISSION_LINE, ProjectType.GENERATION


def project(**kw) -> ProjectDTO:
    base = dict(id=1, utility="Georgia Power", name="Plant X 230 kV breaker", type=SUB,
                voltage_kv=230, confidence=0.9, state="GA")
    return ProjectDTO(**{**base, **kw})


def record(ratio: float, *, scope=CostScope.BREAKER, kv=230.0, size=1.0, utility="Peer Co",
           state="GA", actual=True, year=YEAR) -> CostRecord:
    """A comparable costing `ratio` times its own benchmark."""
    unit = pricing.benchmark_unit(pricing.SCOPES[scope], kv, year)
    return CostRecord(scope=scope, voltage_kv=kv, size=size, cost_musd=ratio * unit * size,
                      cost_year=year, utility=utility, state=state, actual=actual)


# ---------------------------------------------------------------- reading the project


@pytest.mark.parametrize("ptype,name,desc,scope", [
    (LINE, "Gainesville #2 - Bull Shoals 161 Kv Transmission Line, Rebuild", "", "line_rebuild"),
    (LINE, "Anniston - Crooked Creek 115 Kv Tl Reconductor", "", "reconductor"),
    (LINE, "Brown Plant - Fawkes 138 kV",
     "Replace 21.3 miles of transmission line and two station conductors", "reconductor"),
    (LINE, "Rocky Mt - Wilson 115 kV", "Upgrade terminal equipment at both ends", "line_terminal"),
    (LINE, "Line Creek 115 Kv Breaker Replacements", "", "breaker"),
    (SUB, "Oceanway 230 kV substation (new)", "", "new_substation"),
    (SUB, "Ts25-514", "Construct new 230 kV station to interconnect new BESS", "new_substation"),
    (SUB, "Plant Yates 230 Kv Breaker And Half Station", "", "substation_rebuild"),
    (SUB, "Morning Star Tie 230 Kv, Expansion", "", "expansion"),
    (SUB, "Bush River Tie 115/100 Kv Autotransformers, Replace", "", "transformer"),
    (SUB, "Glenwood Springs 115 Kv Cap Bank", "", "reactive"),
    (SUB, "Big Shanty 500 Kv Breaker", "", "breaker"),
    (SUB, "Manchester 115 kV relay retrofit", "", "protection"),
    (SUB, "Jasper 69 kV substation retirement", "", "retirement"),
])
def test_classify_scope_from_text(ptype, name, desc, scope):
    assert pricing.classify_scope(ptype, name, desc) == (CostScope(scope), "text")


def test_unclear_scope_falls_back_to_a_default():
    assert pricing.classify_scope(SUB, "Hamilton County reliability", "") == (
        CostScope.SUBSTATION_GENERAL, "default")
    assert pricing.classify_scope(LINE, "A - B 115 kV", "") == (CostScope.LINE_REBUILD, "default")


def test_supporting_statement_is_not_read_as_scope():
    p = project(name="X 230 kV", raw_excerpt=(
        "Project Name: X\nDescription: Install a 230 kV breaker.\n"
        "Supporting Statement: Serves a new substation for new load."))
    assert pricing.features(p).scope.key == CostScope.BREAKER


def test_size_parsing():
    assert pricing.parse_miles("Rebuild the 24.42 mile-long line") == 24.42
    assert pricing.parse_miles("Rebuild ~21 miles ... Reconductor approximately 50 miles") == 71
    assert pricing.parse_miles("no length here") is None
    assert pricing.parse_mw("Solar (Solar Photovoltaic, 1,200 MW)") == 1200
    assert pricing.parse_count("Install three reactors at the substation") == 3
    assert pricing.parse_count("Replace 2 existing autotransformers") == 2
    assert pricing.parse_count("Install a breaker") == 1


def test_line_size_precedence():
    line = dict(type=LINE, name="A - B 230 kV rebuild",
                raw_excerpt="Description: Rebuild 12 miles of line.")
    assert (pricing.features(project(**line, length_mi=15)).size_source) == "stated"
    f = pricing.features(project(**line))
    assert (f.size, f.size_source) == (12, "text")
    f = pricing.features(project(type=LINE, name="A - B 230 kV rebuild"))
    assert (f.size, f.size_source) == (pricing.ASSUMED_LINE_MILES, "assumed")


def test_planner_scope_overrides_text():
    f = pricing.features(project(cost_scope=CostScope.TRANSFORMER))
    assert (f.scope.key, f.scope_source) == (CostScope.TRANSFORMER, "planner")


# ---------------------------------------------------------------- benchmark


@given(st.floats(1, 1e4), st.integers(1950, 2100), st.integers(1950, 2100))
def test_escalation_round_trips(cost, y1, y2):
    assert pricing.escalate(pricing.escalate(cost, y1, y2), y2, y1) == pytest.approx(cost)


@given(st.floats(1, 1000), st.floats(1, 1000), st.sampled_from(list(pricing.SCOPES.values())))
def test_benchmark_rises_with_voltage(v1, v2, scope):
    lo, hi = sorted((v1, v2))
    assert pricing.benchmark_unit(scope, lo, YEAR) <= pricing.benchmark_unit(scope, hi, YEAR)


def test_benchmark_hits_table_knots():
    new_line = pricing.SCOPES[CostScope.NEW_LINE]
    assert pricing.benchmark_unit(new_line, 230, pricing.BENCHMARK_YEAR) == pytest.approx(2.6)


# ---------------------------------------------------------------- estimate


def test_benchmark_only_estimate():
    e = pricing.estimate(project(), [], year=YEAR)
    assert e.available and e.basis == "benchmark" and e.confidence == "low"
    assert e.central == e.benchmark == e.model
    assert e.low < e.central < e.high
    assert e.comparable_count == 0 and e.scope == CostScope.BREAKER


@pytest.mark.parametrize("kw,reason", [
    (dict(type=GEN), "Generation"),
    (dict(voltage_kv=None), "Voltage unknown"),
    (dict(type=None), "type unknown"),
])
def test_unpriceable_projects_say_why(kw, reason):
    e = pricing.estimate(project(**kw), [], year=YEAR)
    assert not e.available and reason in e.reason and e.central is None


@given(st.integers(1, 40), st.floats(0.3, 3.0))
def test_comparables_pull_estimate_partially(n, ratio):
    """n identical comparables at `ratio` x benchmark move the estimate part of the way;
    more of them move it further (partial pooling)."""
    few = pricing.estimate(project(), [record(ratio)] * n, year=YEAR)
    more = pricing.estimate(project(), [record(ratio)] * (n + 5), year=YEAR)
    pull, pull_more = few.central / few.benchmark, more.central / more.benchmark
    lo, hi = sorted((1.0, ratio))
    tol = 0.005 / few.benchmark  # dollars are rounded to $0.01M
    assert lo - tol <= pull <= hi + tol
    assert abs(math.log(pull_more)) >= abs(math.log(pull)) - 2 * tol
    assert few.basis == "comparables"


def test_many_tight_comparables_give_high_confidence():
    recs = [record(r) for r in (0.9, 1.0, 1.1) * 5]
    e = pricing.estimate(project(), recs, year=YEAR)
    assert e.confidence == "high" and e.effective_n >= 8
    assert e.spread < pricing.estimate(project(), [], year=YEAR).spread


def test_utility_offset_is_shrunk_toward_peers():
    peers = [record(1.0) for _ in range(20)]
    one = pricing.estimate(project(), peers + [record(2.0, utility="Georgia Power")], year=YEAR)
    many = pricing.estimate(
        project(), peers + [record(2.0, utility="georgia power ")] * 20, year=YEAR)
    assert one.utility_comparables == 1 and 0 < one.utility_adjustment < 0.35
    assert many.utility_adjustment > one.utility_adjustment
    assert many.central > one.central


def test_dissimilar_comparables_are_discounted():
    near = pricing.similarity(pricing.SCOPES[CostScope.BREAKER], 230, "GA", record(1), YEAR)
    far = pricing.similarity(
        pricing.SCOPES[CostScope.BREAKER], 230, "GA",
        record(1, scope=CostScope.TRANSFORMER, kv=69, state="TX", actual=False, year=YEAR - 20),
        YEAR,
    )
    other_family = pricing.similarity(
        pricing.SCOPES[CostScope.BREAKER], 230, "GA", record(1, scope=CostScope.NEW_LINE), YEAR)
    assert near == 1.0 and 0 < far < 0.05 and other_family == 0.0


def test_stated_cost_is_used_and_cross_checked():
    p = project(stated_cost_musd=2.0, cost_year=YEAR)
    e = pricing.estimate(p, [], year=YEAR)
    assert e.basis == "stated" and e.central == e.stated == 2.0
    assert e.low < 2.0 < e.high and e.model == e.benchmark
    assert not e.stated_outlier and e.confidence == "high"
    wild = pricing.estimate(project(stated_cost_musd=40.0, cost_year=YEAR), [], year=YEAR)
    assert wild.stated_outlier and wild.confidence == "medium"
    assert "outside" in wild.assumptions[1]


def test_stated_cost_escalates_from_its_year():
    e = pricing.estimate(project(stated_cost_musd=10.0, cost_year=YEAR - 2), [], year=YEAR)
    assert e.central == pytest.approx(10.0 * 1.04**2, abs=0.01)
    dated = project(stated_cost_musd=10.0, start_date=date(YEAR - 1, 1, 1))
    assert pricing.estimate(dated, [], year=YEAR).central == pytest.approx(10.4, abs=0.01)


def test_a_project_is_not_its_own_comparable():
    p = project(stated_cost_musd=3.0, cost_year=YEAR)
    rec = pricing.record_from_project(p, YEAR)
    assert rec is not None and rec.project_id == p.id
    assert pricing.estimate(p, [rec], year=YEAR).comparable_count == 0
    assert pricing.estimate(project(id=2), [rec], year=YEAR).comparable_count == 1


def test_line_costs_without_length_are_not_comparables():
    p = project(type=LINE, name="A - B 230 kV rebuild", stated_cost_musd=30.0)
    assert pricing.record_from_project(p, YEAR) is None
    assert pricing.record_from_project(p.model_copy(update={"length_mi": 10}), YEAR)


def test_reference_rows_parse_and_skip_bad_lines():
    rows = [
        dict(name="A", utility="U", state="GA", scope="breaker", voltage_kv="230", size="1",
             cost_musd="2.1", cost_year="2023", actual="true", source_url="x"),
        dict(name="bad scope", scope="teleporter", voltage_kv="230", cost_musd="1",
             cost_year="2023"),
        dict(name="no cost", scope="breaker", voltage_kv="230", cost_musd="", cost_year="2023"),
    ]
    (rec,) = cost_reference.parse_rows(rows)
    assert rec.scope == CostScope.BREAKER and rec.actual and rec.cost_musd == 2.1
    assert cost_reference.reference_records() == ()  # the shipped file is a header only


# ---------------------------------------------------------------- allocation


def estimates(a: float, b: float):
    ea = pricing.estimate(project(id=1, stated_cost_musd=a, cost_year=YEAR), [], year=YEAR)
    eb = pricing.estimate(project(id=2, stated_cost_musd=b, cost_year=YEAR), [], year=YEAR)
    return ea, eb


money = st.floats(0.5, 500)


@given(money, money, st.floats(0, 1), st.floats(0, 1))
def test_modeled_joint_cost_sits_between_max_and_sum(a, b, synergy, fraction):
    joint = pricing.modeled_joint_cost(a, b, synergy, fraction)
    assert max(a, b) - 1e-9 <= joint <= a + b + 1e-9


@given(money, money, st.floats(0, 1), st.floats(0, 1))
def test_every_split_charges_exactly_the_joint_cost(a, b, synergy, fraction):
    ea, eb = estimates(a, b)
    alloc = pricing.allocate("1-2", ea, eb, synergy=synergy,
                             inputs=AllocationRequest(shareable_fraction=fraction))
    assert alloc.available
    for s in alloc.splits:
        assert s.pays_a + s.pays_b == pytest.approx(alloc.joint_cost, abs=0.02)
    by = {s.key: s for s in alloc.splits}
    # With non-negative savings these two never leave anyone worse off than going alone.
    assert by["standalone"].within_standalone and by["equal_savings"].within_standalone
    assert by["equal_savings"].saves_a == pytest.approx(by["equal_savings"].saves_b, abs=0.02)
    assert alloc.recommended == "equal_savings"


def test_even_split_can_fail_the_standalone_test():
    ea, eb = estimates(2.0, 50.0)
    alloc = pricing.allocate("1-2", ea, eb, synergy=1.0, inputs=AllocationRequest())
    even = next(s for s in alloc.splits if s.key == "equal")
    assert not even.within_standalone and "stand-alone test" in even.note
    assert alloc.savings == pytest.approx(0.3 * 2.0, abs=0.01)


def test_benefit_split_is_recommended_when_it_passes_the_standalone_test():
    ea, eb = estimates(20.0, 30.0)  # joint = 50 - 0.3 * 0.8 * 20 = 45.2
    inputs = AllocationRequest(benefit_a_musd=20, benefit_b_musd=30)
    alloc = pricing.allocate("1-2", ea, eb, synergy=0.8, inputs=inputs)
    benefit = next(s for s in alloc.splits if s.key == "benefit")
    assert alloc.recommended == "benefit"
    assert benefit.share_a == pytest.approx(0.4, abs=1e-3)
    assert benefit.within_standalone and benefit.within_benefits


def test_benefit_split_that_overcharges_one_side_is_not_recommended():
    ea, eb = estimates(20.0, 30.0)
    inputs = AllocationRequest(benefit_a_musd=25, benefit_b_musd=15)
    alloc = pricing.allocate("1-2", ea, eb, synergy=0.8, inputs=inputs)
    benefit = next(s for s in alloc.splits if s.key == "benefit")
    # A would pay 62.5% of $45.2M = $28.25M, more than its $20M stand-alone cost.
    assert not benefit.within_standalone and benefit.within_benefits is False
    assert alloc.recommended == "equal_savings"


def test_usage_split_needs_both_inputs():
    ea, eb = estimates(20.0, 30.0)
    one = pricing.allocate("1-2", ea, eb, synergy=0.5,
                           inputs=AllocationRequest(usage_a_mw=100))
    assert "usage" not in {s.key for s in one.splits}
    both = pricing.allocate("1-2", ea, eb, synergy=0.5,
                            inputs=AllocationRequest(usage_a_mw=600, usage_b_mw=400))
    usage = next(s for s in both.splits if s.key == "usage")
    assert usage.share_a == pytest.approx(0.6, abs=1e-3)


def test_joint_work_that_costs_more_has_no_recommendation():
    ea, eb = estimates(10.0, 10.0)
    alloc = pricing.allocate("1-2", ea, eb, synergy=0.5,
                             inputs=AllocationRequest(joint_cost_musd=25))
    assert alloc.joint_basis == "planner" and alloc.savings == -5
    assert alloc.recommended is None and "more than doing it separately" in (
        alloc.recommended_reason)


def test_allocation_unavailable_when_a_side_cannot_be_priced():
    ea, _ = estimates(10.0, 10.0)
    gen = pricing.estimate(project(id=2, type=GEN), [], year=YEAR)
    alloc = pricing.allocate("1-2", ea, gen, synergy=0.5, inputs=AllocationRequest())
    assert not alloc.available and "Generation" in alloc.reason and alloc.splits == []
