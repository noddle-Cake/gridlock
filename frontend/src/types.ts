// Mirrors the backend DTOs (backend/app/models/dto.py).

export type ProjectType = 'substation' | 'transmission line' | 'generation'
export type DatePrecision = 'year' | 'quarter' | 'month' | 'day'
export type PlanStatus = 'processing' | 'complete' | 'failed'

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

// ---------------------------------------------------------------- search and ask

export interface SearchInterpretation {
  zip: string | null
  zip_found: boolean
  zip_label: string | null
  radius_miles: number | null
  states: string[]
  utilities: string[]
  types: ProjectType[]
  terms: string[]
  fuzzy: boolean
}

export interface CompanySuggestion {
  utility: string
  project_count: number
}

export interface LocationSuggestion {
  kind: 'state' | 'zip'
  code: string
  label: string
  project_count: number
}

export interface SearchHit extends Project {
  miles: number | null
}

export interface SearchResponse {
  query: string
  interpretation: SearchInterpretation
  companies: CompanySuggestion[]
  locations: LocationSuggestion[]
  projects: SearchHit[]
  /** Every match, for filtering the map and the pair list. */
  project_ids: number[]
  total: number
  /** [south, west, north, east] of the placed matches. */
  bounds: [number, number, number, number] | null
  suggest_ai: boolean
}

export interface AskToolCall {
  name: string
  arguments: Record<string, unknown>
  summary: string
}

export interface AskResponse {
  question: string
  answer: string
  projects: Project[]
  tool_calls: AskToolCall[]
}
