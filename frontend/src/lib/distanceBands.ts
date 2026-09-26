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

export const KM_PER_MILE = 1.609344

// Fixed matching radius (the outer edge of the widest band), so distance scores stay the same
// whichever bands are ticked.
export const MAX_RADIUS_MILES = 40 / KM_PER_MILE

export function milesToKm(miles: number): number {
  return miles * KM_PER_MILE
}

/** Short summary for the dropdown button, e.g. "All within 40 km", "None", "Under 1.6 km, 1.6–8 km". */
export function bandSummary(selected: BandId[]): string {
  if (selected.length === DISTANCE_BANDS.length) return 'All within 40 km'
  if (selected.length === 0) return 'None'
  return DISTANCE_BANDS.filter((b) => selected.includes(b.id))
    .map((b) => b.label)
    .join(', ')
}
