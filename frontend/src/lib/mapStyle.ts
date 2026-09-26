import type { PathOptions } from 'leaflet'

import type { Project } from '../types'

export interface MarkerState {
  paired: boolean
  selected: boolean
}

/** Marker styling: paired projects are highlighted, approximate ones hollow + dashed. */
export function markerStyle(
  p: Project,
  color: string,
  s: MarkerState,
): PathOptions & { radius: number } {
  return {
    radius: s.selected ? 11 : s.paired ? 8 : 5,
    color: s.selected ? '#111' : color,
    weight: s.selected ? 3 : s.paired ? 2.5 : 1,
    opacity: s.paired || s.selected ? 1 : 0.55,
    fillColor: color,
    fillOpacity: p.approximate ? 0.08 : s.paired || s.selected ? 0.85 : 0.35,
    dashArray: p.approximate ? '4 3' : undefined,
  }
}
