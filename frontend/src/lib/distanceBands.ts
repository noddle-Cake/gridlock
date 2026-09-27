// Distance bands for the pair filter. They never overlap: a pair falls in exactly one band.
// Ids match the backend's `bands` query param (app/services/matching.py DISTANCE_BANDS_KM).

export type BandId = 'touching' | '1.6' | '8' | '25' | '40'

export interface DistanceBand {
  id: BandId
  label: string
}

export const DISTANCE_BANDS: DistanceBand[] = [
  { id: 'touching', label: 'Touching / crossing' },
  { id: '1.6', label: 'Under 1.6 km' },
  { id: '8', label: '1.6–8 km' },
  { id: '25', label: '8–25 km' },
  { id: '40', label: '25–40 km' },
]

export const ALL_BANDS: BandId[] = DISTANCE_BANDS.map((b) => b.id)

export interface OpportunityType {
  /** Sperry's ranking tier (backend matching.TIERS), also the pair's `tier`. */
  tier: number
  label: string
  detail: string
  /** The distance bands it covers, as the API filters by them. */
  bands: BandId[]
}

/**
 * What two projects this close can share, by Sperry's tiers: each pair is labelled and
 * filtered by this, nearest first. Nearer types also keep the farther types' benefits.
 */
export const OPPORTUNITY_TYPES: OpportunityType[] = [
  {
    tier: 0,
    label: 'Shared outage & crossing',
    detail: 'Touching or crossing: one coordinated outage and crossing design',
    bands: ['touching'],
  },
  {
    tier: 1,
    label: 'Shared land & permits',
    detail: 'Under 1.6 km: right-of-way, access roads and permits',
    bands: ['1.6'],
  },
  {
    tier: 2,
    label: 'Shared laydown yard',
    detail: 'Under 8 km: one laydown yard and shared deliveries',
    bands: ['8'],
  },
  {
    tier: 3,
    label: 'Shared crews & equipment',
    detail: 'Under 40 km: one mobilization of crews, cranes and contractors',
    bands: ['25', '40'],
  },
]

export function opportunityType(tier: number | null | undefined): OpportunityType | undefined {
  return OPPORTUNITY_TYPES.find((t) => t.tier === tier)
}

export const KM_PER_MILE = 1.609344

// Fixed matching radius (the outer edge of the widest band), so distance scores stay the same
// whichever bands are ticked.
export const MAX_RADIUS_MILES = 40 / KM_PER_MILE

export function milesToKm(miles: number): number {
  return miles * KM_PER_MILE
}

/** The opportunity types whose bands are all selected. */
export function selectedTypes(bands: BandId[]): OpportunityType[] {
  return OPPORTUNITY_TYPES.filter((t) => t.bands.every((b) => bands.includes(b)))
}

/** Short summary for the dropdown button: "All opportunity types", "None", or the labels. */
export function typeSummary(bands: BandId[]): string {
  const types = selectedTypes(bands)
  if (types.length === OPPORTUNITY_TYPES.length) return 'All opportunity types'
  if (types.length === 0) return 'None'
  return types.map((t) => t.label).join(', ')
}

/** The bands to query with one type switched on or off, in canonical order. */
export function toggleType(bands: BandId[], type: OpportunityType, on: boolean): BandId[] {
  const next = new Set(bands)
  for (const b of type.bands) {
    if (on) next.add(b)
    else next.delete(b)
  }
  return ALL_BANDS.filter((b) => next.has(b))
}
