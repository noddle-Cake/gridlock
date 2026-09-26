"""Planning-level project costs and shared-cost allocation. Pure functions, no I/O.

Two questions, kept apart on purpose:

1. What will a project cost? A reference-class estimate. A project is reduced to a scope
   (new line, rebuild, breaker, transformer, ...), a voltage and a size (miles for line
   work, a unit count otherwise). A benchmark unit-cost table gives the prior for that
   combination. Comparable projects with known costs (owner-stated costs from ingested
   plans, plus any records in app/data/reference_costs.csv) are escalated to today's
   dollars, expressed as a multiple of their own benchmark, and pull the estimate toward
   what was actually spent. The pull is partial pooling: a few comparables move the
   estimate a little and many move it a lot, and the same holds one level down for the
   owning utility, so one utility's handful of projects can't set its price alone.

2. Who pays what? Given each utility's stand-alone cost and the cost of doing the work
   together, several allocation rules are computed side by side. Each one is checked
   against the stand-alone test: no utility should pay more than going it alone.

The benchmark numbers are planning-level placeholders in BENCHMARK_YEAR dollars, meant
to be calibrated against real cost history. Every result lists the assumptions it rests
on.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass

from app.models.dto import (
    AllocationDTO,
    AllocationRequest,
    ComparableDTO,
    CostEstimateDTO,
    CostSplitDTO,
    ProjectDTO,
)
from app.models.enums import CostScope, ProjectType

BENCHMARK_YEAR = 2025
DEFAULT_ESCALATION = 0.04  # per year, applied to the benchmark and to comparables

# New overhead single-circuit line, $M per mile, by kV (BENCHMARK_YEAR dollars).
LINE_PER_MILE: dict[float, float] = {
    69: 1.3, 115: 1.7, 138: 1.9, 161: 2.1, 230: 2.6, 345: 3.4, 500: 4.4, 765: 5.8,
}
# New substation or switching station, $M each, by its highest kV.
SUBSTATION_NEW: dict[float, float] = {
    69: 8, 115: 13, 138: 16, 161: 19, 230: 27, 345: 45, 500: 70, 765: 100,
}


@dataclass(frozen=True)
class Scope:
    key: CostScope
    label: str
    per_mile: bool  # sized in line miles (LINE_PER_MILE); else in units (SUBSTATION_NEW)
    factor: float  # multiple of that table's new-build cost


SCOPES: dict[CostScope, Scope] = {s.key: s for s in (
    Scope(CostScope.NEW_LINE, "New line", True, 1.0),
    Scope(CostScope.LINE_REBUILD, "Line rebuild", True, 0.75),
    Scope(CostScope.RECONDUCTOR, "Reconductor", True, 0.40),
    Scope(CostScope.UPRATE, "Line uprate (clearances)", True, 0.12),
    Scope(CostScope.LINE_TERMINAL, "Line terminal equipment", False, 0.08),
    Scope(CostScope.NEW_SUBSTATION, "New substation", False, 1.0),
    Scope(CostScope.SUBSTATION_REBUILD, "Substation rebuild", False, 0.70),
    Scope(CostScope.EXPANSION, "Substation expansion / new terminal", False, 0.35),
    Scope(CostScope.TRANSFORMER, "Transformer", False, 0.30),
    Scope(CostScope.REACTIVE, "Capacitor / reactor / STATCOM", False, 0.25),
    Scope(CostScope.BREAKER, "Breaker", False, 0.08),
    Scope(CostScope.PROTECTION, "Protection / relay", False, 0.04),
    Scope(CostScope.RETIREMENT, "Retirement", False, 0.05),
    Scope(CostScope.SUBSTATION_GENERAL, "Substation upgrade (scope unclear)", False, 0.20),
)}

# Partial pooling. The benchmark counts as K_PRIOR comparables of its own; a utility's
# own offset is shrunk as if K_UTILITY peer projects sat at zero offset.
K_PRIOR = 2.0
K_UTILITY = 2.0
SIGMA_PRIOR = 0.45  # log-spread of real costs around the benchmark, same scope/voltage
SIGMA_DEFAULT_SCOPE = 0.35  # extra log-spread when the scope was guessed, not read
SIGMA_ASSUMED_SIZE = 0.5  # extra log-spread when line length had to be assumed
MAX_LOG_RATIO = 1.5  # comparables beyond ~4.5x their benchmark are clipped, not trusted
MIN_WEIGHT = 0.02
Z80 = 1.2816  # 10th-90th percentile of a normal
ASSUMED_LINE_MILES = 10.0
STATED_RANGE = (0.8, 1.3)  # typical accuracy band of an owner's planning estimate
MAX_COMPARABLES_SHOWN = 5


# ---------------------------------------------------------------- reading the project


_EQUIPMENT_RULES: list[tuple[CostScope, re.Pattern[str]]] = [
    (CostScope.REACTIVE, re.compile(
        r"CAPACITOR|\bCAP BANK|REACTOR|STATCOM|\bSVC\b|CONDENSER")),
    (CostScope.TRANSFORMER, re.compile(r"TRANSFORMER|AUTOBANK|\bXFMR|\bBANK\b")),
    (CostScope.BREAKER, re.compile(r"BREAKER|CIRCUIT SWITCHER")),
]
_LINE_RULES: list[tuple[CostScope, re.Pattern[str]]] = [
    (CostScope.RECONDUCTOR, re.compile(
        r"RE-?CONDUCTOR|REPLACE\b.{0,60}\bCONDUCTORS?\b|REPLACE \d+(\.\d+)? MILES")),
    (CostScope.LINE_REBUILD, re.compile(
        r"RE-?BUILD|REPLACE\b.{0,30}\b(STRUCTURES|POLES|TOWERS)")),
    (CostScope.NEW_LINE, re.compile(
        r"\bNEW\b|\bCONSTRUCT|\bBUILD\b|LOOP[- ]?IN|\bEXTEND|\(NEW\)|GREENFIELD")),
    # Station equipment filed under a line ("Line Creek 115 kV Breaker Replacements").
    *_EQUIPMENT_RULES,
    (CostScope.UPRATE, re.compile(r"UPRATE|\bSAG\b|CLEARANCE|INCREASE\b.{0,30}\bRATING")),
    (CostScope.LINE_TERMINAL, re.compile(
        r"TERMINAL|LIMITING|JUMPER|SWITCH|WAVE ?TRAP|RELAY|\bCTS?\b|METER")),
]
_SUBSTATION_RULES: list[tuple[CostScope, re.Pattern[str]]] = [
    (CostScope.RETIREMENT, re.compile(r"RETIRE|DECOMMISSION|DISMANTLE")),
    (CostScope.SUBSTATION_REBUILD, re.compile(
        r"RE-?BUILD|BREAKER[- ]AND[- ]A?[- ]?HALF|REPLACE\b.{0,20}\b(SUBSTATION|STATION)")),
    (CostScope.NEW_SUBSTATION, re.compile(
        r"\bNEW\b.{0,30}\b(SUBSTATION|STATION|SWITCHYARD)|"
        r"CONSTRUCT\b.{0,40}\b(SUBSTATION|STATION|SWITCHYARD)|\(NEW\)|GREENFIELD")),
    (CostScope.EXPANSION, re.compile(
        r"EXPAN|EXPAND|ADDITION|\bADD\b.{0,30}\b(BAY|POSITION|TERMINAL|LINE)|"
        r"\bNEW\b.{0,20}\b(BAY|TERMINAL|POSITION)|INTERCONNECT|TERMINATE|RING BUS")),
    *_EQUIPMENT_RULES,
    (CostScope.PROTECTION, re.compile(r"RELAY|PROTECTION|SCADA|\bRTU\b|FIBER")),
]
_MILES = re.compile(r"(\d+(?:\.\d+)?)\s*(?:-\s*)?(?:CIRCUIT[- ])?(?:MILES?\b|MI\b)")
_MW = re.compile(r"(\d{1,3}(?:,\d{3})+|\d+(?:\.\d+)?)\s*MW\b")
_COUNT_WORDS = {"TWO": 2, "THREE": 3, "FOUR": 4, "FIVE": 5, "SIX": 6}
_COUNT = re.compile(
    r"\b(TWO|THREE|FOUR|FIVE|SIX|[2-6])\s+(?:NEW\s+)?(?:\S+\s+)?"
    r"(BREAKERS|(?:AUTO)?TRANSFORMERS|REACTORS|CAPACITORS|CAPACITOR BANKS|STATCOMS|BANKS)\b"
)


def description(p: ProjectDTO) -> str:
    """The part of the source excerpt that says what the work is.

    SERTP excerpts carry a "Supporting Statement" about *why*, which mentions things like
    "new load" that must not be read as scope.
    """
    text = p.raw_excerpt or ""
    if "Description:" in text:
        text = text.split("Description:", 1)[1]
    return re.split(r"Supporting Statement:", text, maxsplit=1)[0]


def classify_scope(ptype: ProjectType | None, name: str, desc: str) -> tuple[CostScope, str]:
    """Scope from the project name, else its description; ("...", "default") if neither."""
    is_line = ptype == ProjectType.TRANSMISSION_LINE
    rules = _LINE_RULES if is_line else _SUBSTATION_RULES
    for text in (name, desc):
        upper = text.upper()
        for scope, pattern in rules:
            if pattern.search(upper):
                return scope, "text"
    return (CostScope.LINE_REBUILD if is_line else CostScope.SUBSTATION_GENERAL), "default"


def parse_miles(text: str) -> float | None:
    """Total line miles named in the text (distinct figures summed: multi-segment work)."""
    values = {float(m) for m in _MILES.findall(text.upper())}
    total = sum(v for v in values if 0 < v <= 1000)
    return total or None


def parse_mw(text: str) -> float | None:
    m = _MW.search(text.upper())
    return float(m.group(1).replace(",", "")) if m else None


def parse_count(text: str) -> int:
    m = _COUNT.search(text.upper())
    if not m:
        return 1
    word = m.group(1)
    return _COUNT_WORDS.get(word) or int(word)


@dataclass(frozen=True)
class Features:
    """What pricing needs to know about one project."""

    scope: Scope
    scope_source: str  # planner | text | default
    voltage_kv: float | None
    size: float
    size_source: str  # stated | text | assumed | count
    capacity_mw: float | None


def features(p: ProjectDTO) -> Features:
    name, desc = p.name or "", description(p)
    if p.cost_scope:
        key, scope_source = p.cost_scope, "planner"
    else:
        key, scope_source = classify_scope(p.type, name, desc)
    scope = SCOPES[key]
    text = f"{name} {desc}"
    if scope.per_mile:
        if p.length_mi:
            size, size_source = float(p.length_mi), "stated"
        elif miles := parse_miles(text):
            size, size_source = miles, "text"
        else:
            size, size_source = ASSUMED_LINE_MILES, "assumed"
    else:
        size, size_source = float(parse_count(text)), "count"
    return Features(
        scope=scope, scope_source=scope_source,
        voltage_kv=float(p.voltage_kv) if p.voltage_kv else None,
        size=size, size_source=size_source,
        capacity_mw=p.capacity_mw or parse_mw(text),
    )


# ---------------------------------------------------------------- benchmark


def escalate(cost: float, from_year: int, to_year: int, rate: float = DEFAULT_ESCALATION) -> float:
    """Restate `cost` from `from_year` dollars in `to_year` dollars."""
    return cost * (1.0 + rate) ** (to_year - from_year)


def _interpolate(table: dict[float, float], kv: float) -> float:
    """Log-log interpolation between voltage classes; flat beyond the ends."""
    knots = sorted(table)
    if kv <= knots[0]:
        return table[knots[0]]
    if kv >= knots[-1]:
        return table[knots[-1]]
    for lo, hi in zip(knots, knots[1:], strict=False):
        if lo <= kv <= hi:
            t = math.log(kv / lo) / math.log(hi / lo)
            return math.exp((1 - t) * math.log(table[lo]) + t * math.log(table[hi]))
    raise AssertionError("unreachable")


def benchmark_unit(
    scope: Scope, kv: float, year: int, rate: float = DEFAULT_ESCALATION
) -> float:
    """Benchmark $M per mile (per-mile scopes) or per unit, in `year` dollars."""
    table = LINE_PER_MILE if scope.per_mile else SUBSTATION_NEW
    return escalate(_interpolate(table, kv) * scope.factor, BENCHMARK_YEAR, year, rate)


# ---------------------------------------------------------------- comparables


@dataclass(frozen=True)
class CostRecord:
    """A project with a known cost."""

    scope: CostScope
    voltage_kv: float
    size: float  # miles for per-mile scopes, else units
    cost_musd: float  # in cost_year dollars
    cost_year: int
    utility: str = ""
    state: str = ""
    name: str = ""
    actual: bool = False  # completed-project actual vs a planning estimate
    source: str = ""
    project_id: int | None = None  # set for records drawn from the projects table


def record_from_project(p: ProjectDTO, fallback_year: int) -> CostRecord | None:
    """A costed project as a comparable, or None when it can't be normalized."""
    if not p.stated_cost_musd or not p.voltage_kv:
        return None
    f = features(p)
    if f.size_source == "assumed":
        return None  # a line cost with no length says nothing per mile
    year = p.cost_year or (p.start_date.year if p.start_date else fallback_year)
    return CostRecord(
        scope=f.scope.key, voltage_kv=float(p.voltage_kv), size=f.size,
        cost_musd=float(p.stated_cost_musd), cost_year=year, utility=p.utility,
        state=p.state or "", name=p.name or f"Project {p.id}", actual=False,
        source="owner-stated (plan)", project_id=p.id,
    )


def _utility_key(u: str) -> str:
    return u.strip().lower()


def similarity(target: Scope, kv: float, state: str, rec: CostRecord, year: int) -> float:
    """0-1 weight of a comparable. Unit-size differences are normalized away, so this
    only discounts what normalization can't fix."""
    other = SCOPES[rec.scope]
    if other.per_mile != target.per_mile:
        return 0.0
    w = 1.0 if other.key == target.key else 0.3
    w *= math.exp(-abs(math.log(kv / rec.voltage_kv)) / 0.5)
    w *= 0.5 ** (abs(year - rec.cost_year) / 10.0)  # half-weight per decade of age
    w *= 1.0 if state and rec.state and state.upper() == rec.state.upper() else 0.6
    w *= 1.0 if rec.actual else 0.6
    return w


def _clip(x: float) -> float:
    return max(-MAX_LOG_RATIO, min(MAX_LOG_RATIO, x))


# ---------------------------------------------------------------- estimate


def _unavailable(p: ProjectDTO, year: int, reason: str) -> CostEstimateDTO:
    return CostEstimateDTO(project_id=p.id, available=False, reason=reason, dollar_year=year)


def _money(x: float) -> str:
    return f"${x / 1000:.2f}B" if x >= 1000 else f"${x:.1f}M"


def estimate(
    p: ProjectDTO,
    records: list[CostRecord],
    *,
    year: int,
    rate: float = DEFAULT_ESCALATION,
) -> CostEstimateDTO:
    """Planning-level cost of `p` in `year` dollars. `records` may include `p` itself; it
    is skipped so a stated cost never vouches for itself."""
    if p.type == ProjectType.GENERATION:
        return _unavailable(
            p, year, "Generation plant cost belongs to the developer, not a shared "
            "transmission cost; GridMerge prices transmission lines and substations.",
        )
    if p.type is None and not p.cost_scope:
        return _unavailable(p, year, "Project type unknown; set it in Review to price it.")
    if not p.voltage_kv:
        return _unavailable(p, year, "Voltage unknown; set it in Review to price it.")

    f = features(p)
    kv = float(p.voltage_kv)
    bench_unit = benchmark_unit(f.scope, kv, year, rate)
    assumptions = [
        f"Benchmark: {f.scope.label.lower()} at {kv:g} kV ≈ {_money(bench_unit)} per "
        f"{'mile' if f.scope.per_mile else 'unit'} ({year} $, planning-level placeholder "
        f"escalated {rate:.0%}/yr from {BENCHMARK_YEAR}).",
    ]
    if f.scope_source == "default":
        assumptions.append(
            f"Scope not stated; assumed {f.scope.label.lower()}. Set the scope to tighten."
        )
    if f.size_source == "assumed":
        assumptions.append(
            f"Line length not stated; assumed {ASSUMED_LINE_MILES:g} mi. Enter it to tighten."
        )
    elif f.size_source == "text":
        assumptions.append(f"Length {f.size:g} mi read from the project description.")
    elif f.size_source == "count" and f.size > 1:
        assumptions.append(f"{f.size:g} units read from the project description.")

    # Comparables as log multiples of their own benchmark.
    comps: list[tuple[CostRecord, float, float, float]] = []  # rec, weight, log ratio, $now
    for rec in records:
        if rec.project_id == p.id or rec.cost_musd <= 0 or rec.size <= 0:
            continue
        w = similarity(f.scope, kv, p.state or "", rec, year)
        if w < MIN_WEIGHT:
            continue
        now = escalate(rec.cost_musd, rec.cost_year, year, rate)
        ratio = (now / rec.size) / benchmark_unit(SCOPES[rec.scope], rec.voltage_kv, year, rate)
        comps.append((rec, w, _clip(math.log(ratio)), now))

    total_w = sum(w for _, w, _, _ in comps)
    mu_pool = sum(w * r for _, w, r, _ in comps) / (K_PRIOR + total_w)
    owner = _utility_key(p.utility)
    mine = [(w, r) for rec, w, r, _ in comps if _utility_key(rec.utility) == owner]
    mine_w = sum(w for w, _ in mine)
    offset = sum(w * (r - mu_pool) for w, r in mine) / (mine_w + K_UTILITY) if mine else 0.0
    mu = mu_pool + offset

    resid = sum(w * (r - mu_pool) ** 2 for _, w, r, _ in comps) / total_w if total_w else 0.0
    var = (K_PRIOR * SIGMA_PRIOR**2 + total_w * resid) / (K_PRIOR + total_w)
    if f.scope_source == "default":
        var += SIGMA_DEFAULT_SCOPE**2
    if f.size_source == "assumed":
        var += SIGMA_ASSUMED_SIZE**2
    sigma = math.sqrt(var)

    benchmark = bench_unit * f.size
    model = benchmark * math.exp(mu)
    model_low, model_high = model * math.exp(-Z80 * sigma), model * math.exp(Z80 * sigma)
    n_eff = total_w**2 / sum(w * w for _, w, _, _ in comps) if comps else 0.0

    if n_eff >= 8 and sigma <= 0.30:
        confidence = "high"
    elif n_eff >= 3 and sigma <= 0.50:
        confidence = "medium"
    else:
        confidence = "low"
    basis = "comparables" if total_w >= 0.5 else "benchmark"
    if comps:
        assumptions.append(
            f"{len(comps)} comparable project(s), effective weight {total_w:.1f} against the "
            f"benchmark's {K_PRIOR:g}; model = benchmark × {math.exp(mu_pool):.2f}."
        )
    else:
        assumptions.append("No comparable projects with known costs yet: benchmark only.")
    if mine:
        assumptions.append(
            f"{p.utility} runs {math.exp(offset) - 1:+.0%} vs peers after shrinkage "
            f"({len(mine)} of its own project(s))."
        )

    ranked = sorted(comps, key=lambda c: c[1], reverse=True)[:MAX_COMPARABLES_SHOWN]
    shown = [
        ComparableDTO(
            name=rec.name or "Unnamed", utility=rec.utility or "—", year=rec.cost_year,
            cost_musd=round(now, 2), adjusted_musd=round(benchmark * math.exp(r), 2),
            weight=round(w, 3), actual=rec.actual, source=rec.source,
        )
        for rec, w, r, now in ranked
    ]

    result = CostEstimateDTO(
        project_id=p.id, available=True, dollar_year=year,
        central=round(model, 2), low=round(model_low, 2), high=round(model_high, 2),
        basis=basis, confidence=confidence,
        scope=f.scope.key, scope_label=f.scope.label, scope_source=f.scope_source,
        voltage_kv=kv, size=round(f.size, 2), size_unit="mi" if f.scope.per_mile else "units",
        size_source=f.size_source, capacity_mw=f.capacity_mw,
        benchmark=round(benchmark, 2), model=round(model, 2),
        model_low=round(model_low, 2), model_high=round(model_high, 2),
        comparable_count=len(comps), effective_n=round(n_eff, 2),
        spread=round(math.exp(Z80 * sigma) - 1, 3),
        utility_adjustment=round(math.exp(offset) - 1, 3) if mine else None,
        utility_comparables=len(mine), comparables=shown, assumptions=assumptions,
    )

    if p.stated_cost_musd:
        stated_year = p.cost_year or (p.start_date.year if p.start_date else year)
        stated = escalate(float(p.stated_cost_musd), stated_year, year, rate)
        outlier = not (model_low <= stated <= model_high)
        result.central = round(stated, 2)
        result.low = round(stated * STATED_RANGE[0], 2)
        result.high = round(stated * STATED_RANGE[1], 2)
        result.basis = "stated"
        result.confidence = "medium" if outlier else "high"
        result.stated = round(stated, 2)
        result.stated_vs_model = round(stated / model, 3)
        result.stated_outlier = outlier
        result.assumptions.insert(0, (
            f"Owner-stated cost {_money(float(p.stated_cost_musd))} ({stated_year} $) used as "
            f"the estimate; range {STATED_RANGE[0] - 1:+.0%}/{STATED_RANGE[1] - 1:+.0%} "
            "(typical planning-estimate accuracy)."
        ))
        if outlier:
            result.assumptions.insert(1, (
                f"Stated cost is {stated / model:.1f}× the model estimate, outside its 80% "
                "range: check the scope and figure."
            ))
    return result


# ---------------------------------------------------------------- allocation


def modeled_joint_cost(a: float, b: float, synergy: float, shareable_fraction: float) -> float:
    """Cost of doing both projects together. Coordinated work avoids part of the smaller
    project's cost (mobilization, outages, engineering, permitting, right-of-way), in
    proportion to how well the two fit together (`synergy`, 0-1)."""
    synergy = max(0.0, min(1.0, synergy))
    return a + b - shareable_fraction * synergy * min(a, b)


def _split(
    key: str, label: str, pays_a: float, joint: float, sa_a: float, sa_b: float,
    benefits: tuple[float, float] | None, note: str = "",
) -> CostSplitDTO:
    pays_b = joint - pays_a
    eps = 1e-6 * max(1.0, joint)
    within_benefits = None
    if benefits is not None:
        within_benefits = pays_a <= benefits[0] + eps and pays_b <= benefits[1] + eps
    return CostSplitDTO(
        key=key, label=label, pays_a=round(pays_a, 2), pays_b=round(pays_b, 2),
        share_a=round(pays_a / joint, 4) if joint else 0.5,
        saves_a=round(sa_a - pays_a, 2), saves_b=round(sa_b - pays_b, 2),
        within_standalone=pays_a <= sa_a + eps and pays_b <= sa_b + eps,
        within_benefits=within_benefits, note=note,
    )


def _proportional(x: float | None, y: float | None) -> float | None:
    if x is None or y is None or x + y <= 0:
        return None
    return x / (x + y)


def allocate(
    pair_id: str,
    est_a: CostEstimateDTO,
    est_b: CostEstimateDTO,
    *,
    synergy: float,
    inputs: AllocationRequest,
) -> AllocationDTO:
    """Stand-alone vs joint cost, and several ways to split the joint cost."""
    base = AllocationDTO(
        pair_id=pair_id, available=False, dollar_year=est_a.dollar_year,
        estimate_a=est_a, estimate_b=est_b,
    )
    if not (est_a.available and est_b.available):
        missing = [e for e in (est_a, est_b) if not e.available]
        base.reason = " ".join(e.reason or "" for e in missing).strip() or "No estimate."
        return base

    sa_a, sa_b = float(est_a.central), float(est_b.central)
    assumptions: list[str] = []
    if inputs.joint_cost_musd is not None:
        joint = low = high = float(inputs.joint_cost_musd)
        joint_basis = "planner"
        assumptions.append(f"Joint cost {_money(joint)} entered by the planner.")
    else:
        joint = modeled_joint_cost(sa_a, sa_b, synergy, inputs.shareable_fraction)
        low = modeled_joint_cost(est_a.low, est_b.low, synergy, inputs.shareable_fraction)
        high = modeled_joint_cost(est_a.high, est_b.high, synergy, inputs.shareable_fraction)
        joint_basis = "modeled"
        assumptions.append(
            f"Joint cost modeled: up to {inputs.shareable_fraction:.0%} of the smaller "
            f"project's cost is shared work (mobilization, outages, engineering, permitting, "
            f"right-of-way), scaled by the pair's {synergy:.0%} coordination score. Enter a "
            "joint estimate to replace it."
        )
    savings = sa_a + sa_b - joint

    benefits = None
    if inputs.benefit_a_musd is not None and inputs.benefit_b_musd is not None:
        benefits = (inputs.benefit_a_musd, inputs.benefit_b_musd)

    def split(key: str, label: str, pays_a: float, note: str = "") -> CostSplitDTO:
        return _split(key, label, pays_a, joint, sa_a, sa_b, benefits, note)

    splits = [
        split("equal", "50/50", joint / 2, "Baseline only: ignores who needs what."),
        split("standalone", "Stand-alone cost", joint * sa_a / (sa_a + sa_b),
              "Each pays in proportion to what it would spend alone."),
    ]
    half = savings / 2
    equal_savings = max(0.0, min(joint, sa_a - half))
    splits.append(split(
        "equal_savings", "Equal savings", equal_savings,
        "Each pays its stand-alone cost minus half the joint savings (Shapley value)."
        + (" Clamped: the savings exceed one side's stand-alone cost." if
           equal_savings != sa_a - half else ""),
    ))
    usage = _proportional(inputs.usage_a_mw, inputs.usage_b_mw)
    usage_note = "Proportional to expected use (MW)."
    if usage is None and inputs.usage_a_mw is None and inputs.usage_b_mw is None:
        usage = _proportional(est_a.capacity_mw, est_b.capacity_mw)
        usage_note = "Proportional to stated capacity (MW); enter expected use to refine."
    if usage is not None:
        splits.append(split("usage", "Usage (MW)", joint * usage, usage_note))
    benefit = _proportional(*benefits) if benefits else None
    if benefit is not None:
        splits.append(split(
            "benefit", "Benefits", joint * benefit,
            "Proportional to quantified benefits (avoided upgrades, losses, congestion, "
            "reliability): roughly commensurate with benefits, as FERC requires.",
        ))

    by_key = {s.key: s for s in splits}
    if savings < 0:
        recommended = None
        reason = (
            f"Doing the work jointly costs {_money(-savings)} more than doing it separately, "
            "so no split leaves both utilities better off. Build separately unless there are "
            "benefits beyond cost."
        )
    elif "benefit" in by_key and by_key["benefit"].within_standalone:
        recommended = "benefit"
        reason = "Quantified benefits are the most defensible basis and this split leaves " \
            "neither utility worse off than building alone."
    elif "usage" in by_key and by_key["usage"].within_standalone and \
            inputs.usage_a_mw is not None:
        recommended = "usage"
        reason = "Expected use is the best basis available and this split leaves neither " \
            "utility worse off than building alone."
    else:
        recommended = "equal_savings"
        reason = "Splits the savings from working together evenly; each utility pays less " \
            "than going it alone. Add benefit estimates for a benefit-based split."
    for s in splits:
        if not s.within_standalone:
            s.note += " Fails the stand-alone test: one utility would do better alone."
        if s.within_benefits is False:
            s.note += " Charges one utility more than its stated benefit."
        s.note = s.note.strip()

    return AllocationDTO(
        pair_id=pair_id, available=True, dollar_year=est_a.dollar_year,
        estimate_a=est_a, estimate_b=est_b,
        standalone_a=round(sa_a, 2), standalone_b=round(sa_b, 2),
        joint_cost=round(joint, 2), joint_low=round(min(low, high), 2),
        joint_high=round(max(low, high), 2), joint_basis=joint_basis,
        savings=round(savings, 2), splits=splits, recommended=recommended,
        recommended_reason=reason, assumptions=assumptions,
    )
