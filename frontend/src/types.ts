// Mirrors the backend DTOs (backend/app/models/dto.py).

export type ProjectType = 'substation' | 'transmission line' | 'generation'
export type DatePrecision = 'year' | 'quarter' | 'month' | 'day'
export type PlanStatus = 'processing' | 'complete' | 'failed'
export type CostScope =
  | 'new_line'
  | 'line_rebuild'
  | 'reconductor'
  | 'uprate'
  | 'line_terminal'
  | 'new_substation'
  | 'substation_rebuild'
  | 'expansion'
  | 'transformer'
  | 'reactive'
  | 'breaker'
  | 'protection'
  | 'retirement'
  | 'substation_general'

export interface Project {
  id: number
  plan_id: string | null
  utility: string
  state: string | null
  name: string | null
  type: ProjectType | null
  voltage_kv: number | null
  location_ref: string | null
  lat: number | null
  lng: number | null
  start_date: string | null
  end_date: string | null
  start_precision: DatePrecision | null
  end_precision: DatePrecision | null
  confidence: number
  source_url: string | null
  source_page: number | null
  raw_excerpt: string | null
  reviewed: boolean
  approximate: boolean
  requires_review: boolean
  /** Pricing inputs; null = not stated (pricing may still read length/MW from the text). */
  length_mi?: number | null
  capacity_mw?: number | null
  /** The owner's own cost estimate, $M of cost_year dollars. */
  stated_cost_musd?: number | null
  cost_year?: number | null
  /** Planner override of the scope pricing reads from the project text. */
  cost_scope?: CostScope | null
}

export type ProjectPatch = Partial<{
  utility: string
  state: string | null
  name: string | null
  type: ProjectType | null
  voltage_kv: number | null
  location_ref: string | null
  lat: number | null
  lng: number | null
  start_date: string | null
  end_date: string | null
  source_url: string | null
  source_page: number | null
  reviewed: boolean
  approximate: boolean
  length_mi: number | null
  stated_cost_musd: number | null
  cost_year: number | null
  cost_scope: CostScope | null
}>

export interface ScoreFactors {
  distance: number
  overlap: number
  type_similarity: number
  voltage_similarity: number
  composite: number
  indeterminate_factors: string[]
}

export interface CoordinationBrief {
  pair_id: string
  text: string
  generated_at: string
  stale: boolean
}

/** Projects as embedded in a pair: GET /overlaps leaves out the source excerpt. */
export type PairProject = Omit<Project, 'raw_excerpt'>

export interface CoordinationPair {
  id: string
  project_a: PairProject
  project_b: PairProject
  miles: number
  /** Days both build windows share; 0 when they don't meet or a date is unknown. */
  overlap_days: number
  /** Shared days / days either project is building (0–1); null when either is undated. */
  overlap_ratio: number | null
  /** Days between the two in-service dates; null when either is undated. */
  time_gap_days: number | null
  /** The shared stretch of the two build windows, when there is one. */
  window_start: string | null
  window_end: string | null
  scores: ScoreFactors
  brief: CoordinationBrief | null
}

export interface OverlapsResponse {
  radius: number
  pairs: CoordinationPair[]
}

export interface IngestResult {
  plan_id: string
  utility: string
  source_url: string
  utility_stored: boolean
  source_url_stored: boolean
  status: 'processing'
}

export interface Plan {
  plan_id: string
  utility: string
  source_url: string
  filename: string | null
  detected_format: string
  status: PlanStatus
  error: string | null
  project_count: number
  created_at: string
  page_range?: string | null
}

export interface ApiErrorBody {
  code: string
  message: string
  field?: string
  fields?: string[]
  detected_format?: string
}

// Existing transmission lines (HIFLD reference layer, GET /lines). Not planned projects.
export interface LineProperties {
  owner: string | null
  owner_norm: string | null
  voltage_kv: number | null
  volt_class: string | null
  status: string | null
  sub_1: string | null
  sub_2: string | null
}

export interface LineFeature {
  type: 'Feature'
  id: string
  geometry: { type: 'MultiLineString'; coordinates: [number, number][][] }
  properties: LineProperties
}

export interface LineCollection {
  type: 'FeatureCollection'
  features: LineFeature[]
}

// Pricing (backend services/pricing.py). All money is $M in `dollar_year` dollars.

export interface Comparable {
  name: string
  utility: string
  year: number
  cost_musd: number
  /** Rescaled to the target's scope, voltage and size. */
  adjusted_musd: number
  weight: number
  actual: boolean
  source: string
}

export interface CostEstimate {
  project_id: number
  available: boolean
  reason: string | null
  dollar_year: number
  central: number | null
  low: number | null
  high: number | null
  basis: 'stated' | 'comparables' | 'benchmark' | null
  confidence: 'high' | 'medium' | 'low' | null
  scope: CostScope | null
  scope_label: string | null
  scope_source: 'planner' | 'text' | 'default' | null
  voltage_kv: number | null
  size: number | null
  size_unit: 'mi' | 'units' | null
  size_source: 'stated' | 'text' | 'assumed' | 'count' | null
  capacity_mw: number | null
  benchmark: number | null
  model: number | null
  model_low: number | null
  model_high: number | null
  stated: number | null
  stated_vs_model: number | null
  stated_outlier: boolean
  comparable_count: number
  effective_n: number
  spread: number | null
  utility_adjustment: number | null
  utility_comparables: number
  comparables: Comparable[]
  assumptions: string[]
}

export type AllocationInputs = Partial<{
  joint_cost_musd: number
  shareable_fraction: number
  usage_a_mw: number
  usage_b_mw: number
  benefit_a_musd: number
  benefit_b_musd: number
}>

export interface CostSplit {
  key: 'equal' | 'standalone' | 'equal_savings' | 'usage' | 'benefit'
  label: string
  pays_a: number
  pays_b: number
  share_a: number
  saves_a: number
  saves_b: number
  within_standalone: boolean
  within_benefits: boolean | null
  note: string
}

export interface Allocation {
  pair_id: string
  available: boolean
  reason: string | null
  dollar_year: number
  estimate_a: CostEstimate
  estimate_b: CostEstimate
  standalone_a: number | null
  standalone_b: number | null
  joint_cost: number | null
  joint_low: number | null
  joint_high: number | null
  joint_basis: 'modeled' | 'planner' | null
  savings: number | null
  splits: CostSplit[]
  recommended: CostSplit['key'] | null
  recommended_reason: string | null
  assumptions: string[]
}
