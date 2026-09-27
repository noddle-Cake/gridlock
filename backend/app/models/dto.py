from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, computed_field, model_validator

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

    @computed_field
    @property
    def ownership_review_required(self) -> bool:
        from app.services.owners import ownership_review_required

        return ownership_review_required(self.utility)

    @computed_field
    @property
    def operating_as_of(self) -> date | None:
        from app.services.project_status import operating_evidence

        evidence = operating_evidence(self.source_url, self.name)
        return evidence.as_of if evidence else None

    @computed_field
    @property
    def operating_source_url(self) -> str | None:
        from app.services.project_status import operating_evidence

        evidence = operating_evidence(self.source_url, self.name)
        return evidence.source_url if evidence else None


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
    # "llm" = drafted by the model; "template" = built from the pair's facts because no
    # model is configured.
    source: Literal["llm", "template"] = "llm"


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
    # The timing rules every pair met (matching.Rules): both projects in service on or after
    # planning_from, building together for at least min_overlap_days.
    planning_from: date
    min_overlap_days: int
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


# ---------------------------------------------------------------- search and ask


class SearchInterpretationDTO(BaseModel):
    """How GET /search read the query, so the UI can echo it back ("FPL · FL · 33157")."""

    zip: str | None = None
    zip_found: bool = False  # the ZIP is in the Census ZCTA gazetteer
    zip_label: str | None = None  # e.g. "ZIP 33157 · near Miami-Dade County, FL"
    radius_miles: float | None = None  # ZIP searches match projects within this distance
    states: list[str] = []
    utilities: list[str] = []
    types: list[ProjectType] = []
    terms: list[str] = []
    fuzzy: bool = False  # nothing matched exactly; results are trigram near-matches


class CompanySuggestionDTO(BaseModel):
    utility: str
    project_count: int


class LocationSuggestionDTO(BaseModel):
    kind: Literal["state", "zip"]
    code: str  # "GA" or "33157"
    label: str
    project_count: int


class SearchHitDTO(ProjectDTO):
    miles: float | None = None  # distance from the searched ZIP code


class SearchResponse(BaseModel):
    query: str
    interpretation: SearchInterpretationDTO
    companies: list[CompanySuggestionDTO]
    locations: list[LocationSuggestionDTO]
    projects: list[SearchHitDTO]  # the first `limit` matches
    project_ids: list[int]  # every match, for filtering the map and pair list
    total: int
    bounds: list[float] | None = None  # [south, west, north, east], centred on a searched ZIP
    suggest_ai: bool = False  # reads like a question: offer "Ask GridMerge" first


class LoginRequest(BaseModel):
    username: str = Field(max_length=320)
    password: str = Field(max_length=256)


class SessionDTO(BaseModel):
    required: bool  # sign-in is configured on this server
    authenticated: bool
    username: str | None = None
    guests: bool = False  # visitors without a session may browse, without AI or edits


class AskRequest(BaseModel):
    question: str = Field(min_length=1, max_length=500)


class AskToolCallDTO(BaseModel):
    name: str
    arguments: dict
    summary: str  # e.g. "12 projects"


class AskResponse(BaseModel):
    question: str
    answer: str
    projects: list[ProjectDTO]  # the projects the answer cites, else the ones it looked at
    tool_calls: list[AskToolCallDTO]
