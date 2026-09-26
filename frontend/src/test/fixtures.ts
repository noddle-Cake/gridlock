import type { Allocation, CoordinationPair, CostEstimate, Project } from '../types'

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
    overlap_days: 213,
    overlap_ratio: 0.58,
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

export function estimate(overrides: Partial<CostEstimate> = {}): CostEstimate {
  return {
    project_id: 1,
    available: true,
    reason: null,
    dollar_year: 2026,
    central: 2.2,
    low: 1.3,
    high: 4.0,
    basis: 'benchmark',
    confidence: 'low',
    scope: 'breaker',
    scope_label: 'Breaker',
    scope_source: 'text',
    voltage_kv: 115,
    size: 1,
    size_unit: 'units',
    size_source: 'count',
    capacity_mw: null,
    benchmark: 2.2,
    model: 2.2,
    model_low: 1.3,
    model_high: 4.0,
    stated: null,
    stated_vs_model: null,
    stated_outlier: false,
    comparable_count: 0,
    effective_n: 0,
    spread: 0.78,
    utility_adjustment: null,
    utility_comparables: 0,
    comparables: [],
    assumptions: ['Benchmark: breaker at 115 kV.'],
    ...overrides,
  }
}

export function allocation(overrides: Partial<Allocation> = {}): Allocation {
  return {
    pair_id: '1-2',
    available: true,
    reason: null,
    dollar_year: 2026,
    estimate_a: estimate(),
    estimate_b: estimate({ project_id: 2, central: 40, low: 30, high: 52, basis: 'stated' }),
    standalone_a: 2.2,
    standalone_b: 40,
    joint_cost: 41.8,
    joint_low: 31,
    joint_high: 55,
    joint_basis: 'modeled',
    savings: 0.4,
    splits: [
      {
        key: 'equal', label: '50/50', pays_a: 20.9, pays_b: 20.9, share_a: 0.5,
        saves_a: -18.7, saves_b: 19.1, within_standalone: false, within_benefits: null,
        note: 'Baseline only.',
      },
      {
        key: 'equal_savings', label: 'Equal savings', pays_a: 2.0, pays_b: 39.8,
        share_a: 0.048, saves_a: 0.2, saves_b: 0.2, within_standalone: true,
        within_benefits: null, note: 'Shapley value.',
      },
    ],
    recommended: 'equal_savings',
    recommended_reason: 'Splits the savings evenly.',
    assumptions: ['Joint cost modeled.'],
    ...overrides,
  }
}
