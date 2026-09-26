from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.models.enums import CostScope, DatePrecision, PlanStatus, ProjectType


class ProjectDTO(BaseModel):
    id: int
    plan_id: str | None = None
    utility: str
    state: str | None = None
    name: str | None = None
    type: ProjectType | None = None
    voltage_kv: int | None = None
    location_ref: str | None = None
    lat: float | None = None
    lng: float | None = None
    start_date: date | None = None
    end_date: date | None = None
    start_precision: DatePrecision | None = None
    end_precision: DatePrecision | None = None
    confidence: float
    source_url: str | None = None
    source_page: int | None = None
    raw_excerpt: str | None = None
    reviewed: bool = False
    approximate: bool = False
    requires_review: bool = False
    # Pricing inputs; NULL = not stated (pricing may still read length/MW from the text).
    length_mi: float | None = None
    capacity_mw: float | None = None
    stated_cost_musd: float | None = None  # the owner's own estimate, $M
    cost_year: int | None = None  # dollar year of stated_cost_musd
    cost_scope: CostScope | None = None  # planner override of the scope read from the text


class ProjectPatch(BaseModel):
    """Body of PATCH /projects/{id}. Every field is optional; unknown fields are rejected."""

    model_config = ConfigDict(extra="forbid")

    utility: str | None = Field(default=None, min_length=1)
    state: str | None = None
    name: str | None = None
    type: ProjectType | None = None
    voltage_kv: float | None = Field(default=None, ge=0.1, le=2000)
    location_ref: str | None = None
    lat: float | None = Field(default=None, ge=-90, le=90)
    lng: float | None = Field(default=None, ge=-180, le=180)
    start_date: date | None = None
    end_date: date | None = None
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    source_url: str | None = None
    source_page: int | None = Field(default=None, ge=1)
    raw_excerpt: str | None = Field(default=None, max_length=2000)
    reviewed: bool | None = None
    approximate: bool | None = None
    length_mi: float | None = Field(default=None, gt=0, le=2000)
    capacity_mw: float | None = Field(default=None, gt=0, le=20000)
    stated_cost_musd: float | None = Field(default=None, gt=0, le=100000)
    cost_year: int | None = Field(default=None, ge=1950, le=2100)
    cost_scope: CostScope | None = None

    @model_validator(mode="after")
    def _lat_lng_together(self) -> "ProjectPatch":
        sent = self.model_fields_set
        if ("lat" in sent) != ("lng" in sent):
            raise ValueError("lat and lng must be edited together")
        if "lat" in sent and (self.lat is None) != (self.lng is None):
            raise ValueError("lat and lng must both be set or both be null")
        if "utility" in sent and self.utility is None:
            raise ValueError("utility cannot be empty")
        if "reviewed" in sent and self.reviewed is None:
            raise ValueError("reviewed must be true or false")
        return self


class ScoreFactorsDTO(BaseModel):
    distance: float
    overlap: float
    type_similarity: float
    voltage_similarity: float
    composite: float
    indeterminate_factors: list[str] = []


class CoordinationBriefDTO(BaseModel):
    pair_id: str
    text: str
    generated_at: datetime
    stale: bool = False


class CoordinationPairDTO(BaseModel):
    id: str
    project_a: ProjectDTO
    project_b: ProjectDTO
    miles: float
    overlap_days: int  # days both build windows share (0 = none or unknown)
    # Shared days / days either project is building (0-1); None when either is undated.
    overlap_ratio: float | None = None
    time_gap_days: int | None = None  # days between in-service dates; None when undated
    window_start: date | None = None  # the shared build window, when there is one
    window_end: date | None = None
    scores: ScoreFactorsDTO
    brief: CoordinationBriefDTO | None = None


class OverlapsResponse(BaseModel):
    radius: float
    pairs: list[CoordinationPairDTO]


class IngestResult(BaseModel):
    plan_id: str
    utility: str
    source_url: str
    utility_stored: bool = True
    source_url_stored: bool = True
    status: Literal["processing"] = "processing"


class PlanDTO(BaseModel):
    plan_id: str
    utility: str
    source_url: str
    filename: str | None
    detected_format: str
    status: PlanStatus
    error: str | None = None
    project_count: int = 0
    created_at: datetime
    page_range: str | None = None


class LineOwnerDTO(BaseModel):
    """One owner in the HIFLD reference layer (GET /lines/owners)."""

    owner: str | None  # None groups lines HIFLD publishes without an owner
    line_count: int
    km: float
    min_kv: float | None = None
    max_kv: float | None = None
    raw_names: list[str] = []


# ---------------------------------------------------------------- pricing (services/pricing.py)


class ComparableDTO(BaseModel):
    """A project with a known cost that informed an estimate."""

    name: str
    utility: str
    year: int
    cost_musd: float  # escalated to the estimate's dollar year
    adjusted_musd: float  # rescaled to the target's scope, voltage and size
    weight: float  # 0-1 similarity to the target
    actual: bool  # completed-project actual (True) or a planning estimate (False)
    source: str


class CostEstimateDTO(BaseModel):
    """Planning-level cost of one project, in $M of `dollar_year` dollars.

    `central` is the number to use: the owner's stated cost when there is one, otherwise
    the model (benchmark pulled toward comparables). `low`/`high` bound the middle 80%.
    """

    project_id: int
    available: bool
    reason: str | None = None  # why there is no estimate, when unavailable
    dollar_year: int
    central: float | None = None
    low: float | None = None
    high: float | None = None
    basis: Literal["stated", "comparables", "benchmark"] | None = None
    confidence: Literal["high", "medium", "low"] | None = None
    scope: CostScope | None = None
    scope_label: str | None = None
    scope_source: Literal["planner", "text", "default"] | None = None
    voltage_kv: float | None = None
    size: float | None = None  # miles for per-mile scopes, else units
    size_unit: Literal["mi", "units"] | None = None
    size_source: Literal["stated", "text", "assumed", "count"] | None = None
    capacity_mw: float | None = None  # stated or read from the text; feeds the usage split
    benchmark: float | None = None  # benchmark table alone
    model: float | None = None  # benchmark + comparables (== central unless stated)
    model_low: float | None = None
    model_high: float | None = None
    stated: float | None = None  # owner's stated cost, escalated
    stated_vs_model: float | None = None  # stated / model
    stated_outlier: bool = False  # stated cost falls outside the model's 80% range
    comparable_count: int = 0
    effective_n: float = 0.0  # Kish effective sample size of the weighted comparables
    spread: float | None = None  # +/- fraction of the 80% range around central (model)
    utility_adjustment: float | None = None  # e.g. 0.12 = this owner runs 12% above peers
    utility_comparables: int = 0
    comparables: list[ComparableDTO] = []
    assumptions: list[str] = []


class AllocationRequest(BaseModel):
    """Optional planner inputs for POST /overlaps/{id}/allocation. $ are $M."""

    model_config = ConfigDict(extra="forbid")

    joint_cost_musd: float | None = Field(default=None, gt=0, le=100000)
    shareable_fraction: float = Field(default=0.3, ge=0, le=1)
    usage_a_mw: float | None = Field(default=None, ge=0, le=100000)
    usage_b_mw: float | None = Field(default=None, ge=0, le=100000)
    benefit_a_musd: float | None = Field(default=None, ge=0, le=100000)
    benefit_b_musd: float | None = Field(default=None, ge=0, le=100000)


class CostSplitDTO(BaseModel):
    key: Literal["equal", "standalone", "equal_savings", "usage", "benefit"]
    label: str
    pays_a: float
    pays_b: float
    share_a: float  # 0-1
    saves_a: float  # stand-alone cost minus what this rule charges (negative = worse off)
    saves_b: float
    within_standalone: bool  # neither utility pays more than building alone
    within_benefits: bool | None = None  # neither pays more than its benefit (if given)
    note: str = ""


class AllocationDTO(BaseModel):
    pair_id: str
    available: bool
    reason: str | None = None
    dollar_year: int
    estimate_a: CostEstimateDTO
    estimate_b: CostEstimateDTO
    standalone_a: float | None = None
    standalone_b: float | None = None
    joint_cost: float | None = None
    joint_low: float | None = None
    joint_high: float | None = None
    joint_basis: Literal["modeled", "planner"] | None = None
    savings: float | None = None  # standalone_a + standalone_b - joint_cost
    splits: list[CostSplitDTO] = []
    recommended: str | None = None
    recommended_reason: str | None = None
    assumptions: list[str] = []
