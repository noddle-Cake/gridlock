from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.models.enums import DatePrecision, PlanStatus, ProjectType


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
    # Straight route between the endpoint substations as [lat, lng] points; None = a point.
    route: list[tuple[float, float]] | None = None
    cost_usd: int | None = None  # estimated total cost (USD) when the filing publishes it
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


class ImpactItemDTO(BaseModel):
    label: str
    low: int  # USD
    high: int
    basis: str
    acres: float | None = None
    needs_timing: bool = False  # only realised if the build windows overlap


class ImpactDTO(BaseModel):
    """Rough coordination value (services/impact.py). Assumption-based ranges in USD."""

    items: list[ImpactItemDTO]
    total_low: int  # items realisable on the current schedules
    total_high: int
    if_aligned_low: int  # every item, if the schedules were aligned
    if_aligned_high: int
    windows_overlap: bool
    acres: float | None = None  # right-of-way land that could be shared
    assumptions: list[str] = []


class CoordinationPairDTO(BaseModel):
    id: str
    project_a: ProjectDTO
    project_b: ProjectDTO
    miles: float
    # Distance band id (matching.DISTANCE_BANDS_KM); the ranking tier comes from it.
    band: str | None = None
    tier: int | None = None  # 0 = touching ... 3 = crews & equipment (matching.TIERS)
    overlap_days: int  # days both build windows share (0 = none or unknown)
    # Shared days / days either project is building (0-1); None when either is undated.
    overlap_ratio: float | None = None
    time_gap_days: int | None = None  # days between in-service dates; None when undated
    window_start: date | None = None  # the shared build window, when there is one
    window_end: date | None = None
    # Each project's build window [start, end] as scored (services/timing.py: a plan with only
    # an in-service date builds for the 12 months before it); None when undated.
    build_a: tuple[date, date] | None = None
    build_b: tuple[date, date] | None = None
    shared_km: float | None = None  # km of shared corridor when both are routed lines
    # The closest points of the two shapes as [[lat, lng], [lat, lng]]: what `miles`
    # measures. Equal points mean the projects touch.
    link: list[tuple[float, float]] | None = None
    scores: ScoreFactorsDTO
    impact: ImpactDTO | None = None
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
