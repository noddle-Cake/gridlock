import type { CoordinationPair, Project } from '../types'

export function project(overrides: Partial<Project> = {}): Project {
  return {
    id: 1,
    plan_id: null,
    utility: 'Keystone Electric',
    state: 'PA',
    name: 'Hanover breakers',
    type: 'substation',
    voltage_kv: 115,
    location_ref: 'Hanover, PA',
    lat: 39.8,
    lng: -76.98,
    start_date: '2026-04-01',
    end_date: '2026-09-30',
    start_precision: 'quarter',
    end_precision: 'quarter',
    confidence: 0.9,
    source_url: 'http://localhost:8000/samples/plan.pdf',
    source_page: 2,
    raw_excerpt: 'Hanover 115 kV breaker replacement',
    reviewed: false,
    approximate: false,
    requires_review: false,
    ...overrides,
  }
}

export function pair(overrides: Partial<CoordinationPair> = {}): CoordinationPair {
  return {
    id: '1-2',
    project_a: project(),
    project_b: project({
      id: 2,
      utility: 'Chesapeake Power',
      name: 'Westminster breakers',
      location_ref: 'Westminster, MD',
      lat: 39.58,
      lng: -77.0,
      confidence: 0.5,
      approximate: true,
    }),
    miles: 15.62,
    band: '25',
    tier: 3,
    overlap_days: 213,
    time_gap_days: 0,
    window_start: '2026-04-01',
    window_end: '2026-10-30',
    scores: {
      distance: 0.38,
      overlap: 0.58,
      type_similarity: 1,
      voltage_similarity: 0,
      composite: 0.6,
      indeterminate_factors: ['voltage_similarity'],
    },
    brief: null,
    ...overrides,
  }
}
