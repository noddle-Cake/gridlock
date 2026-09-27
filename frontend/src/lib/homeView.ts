export type LatLng = [number, number]

/**
 * Contiguous US (lower 48), padded a little past Key West, Cape Flattery and West Quoddy
 * Head. Alaska, Hawaii and the territories fall outside it.
 */
export const LOWER_48: { south: number; north: number; west: number; east: number } = {
  south: 24,
  north: 50,
  west: -125.5,
  east: -66.5,
}

export function inLower48([lat, lng]: LatLng): boolean {
  return lat >= LOWER_48.south && lat <= LOWER_48.north && lng >= LOWER_48.west && lng <= LOWER_48.east
}

/**
 * The points the map opens on: those in the lower 48, where nearly every project and pair
 * is. Fitting Alaska, Hawaii and Puerto Rico too frames most of North America and shrinks
 * the mainland to a third of the map. Falls back to every point when none are in the lower
 * 48 (an Alaska-only dataset still opens on its projects), and to null when there are none.
 */
export function homePoints(points: readonly LatLng[]): LatLng[] | null {
  if (!points.length) return null
  const mainland = points.filter(inLower48)
  return mainland.length ? mainland : [...points]
}
