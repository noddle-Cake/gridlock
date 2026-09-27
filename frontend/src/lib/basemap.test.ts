import type { FeatureCollection } from 'geojson'
import { topology } from 'topojson-server'
import { describe, expect, it } from 'vitest'

import {
  chunkLines,
  countyLines,
  type LabelCandidate,
  layoutLabels,
  minPlacePopulation,
  placeTier,
  signPoints,
  stateBorders,
} from './basemap'

describe('minPlacePopulation', () => {
  it('admits smaller towns as the map zooms in', () => {
    const zooms = [4, 5, 6, 7, 8, 9, 10, 11, 13]
    const mins = zooms.map(minPlacePopulation)
    for (let i = 1; i < mins.length; i++) expect(mins[i]).toBeLessThanOrEqual(mins[i - 1])
    expect(minPlacePopulation(12)).toBe(0)
  })

  it('sizes labels by population', () => {
    expect(placeTier(500_000)).toBe('city')
    expect(placeTier(20_000)).toBe('town')
    expect(placeTier(900)).toBe('village')
  })
})

const box = { left: 0, top: 0, width: 40, height: 10 }
const cand = (key: string, x: number, y: number, extra: Partial<LabelCandidate> = {}) => ({
  key,
  x,
  y,
  box,
  text: key,
  ...extra,
})

describe('layoutLabels', () => {
  it('keeps the first of two overlapping labels', () => {
    const kept = layoutLabels([cand('big', 0, 0), cand('small', 20, 5), cand('far', 200, 0)])
    expect([...kept]).toEqual(['big', 'far'])
  })

  it('drops repeats of the same highway sign that are too close together', () => {
    const sign = (key: string, x: number) => cand(key, x, 0, { text: 'I-95', repeatGap: 150 })
    const kept = layoutLabels([sign('a', 0), sign('b', 100), sign('c', 300)])
    expect([...kept]).toEqual(['a', 'c'])
  })

  it('stops at the label limit', () => {
    const many = Array.from({ length: 10 }, (_, i) => cand(`l${i}`, i * 100, 0))
    expect(layoutLabels(many, 3, 4).size).toBe(4)
  })
})

describe('signPoints', () => {
  it('spaces signs evenly along a line, starting half a gap in', () => {
    const pts = signPoints(
      [
        [
          [0, 0],
          [1, 0],
        ],
      ],
      0.25,
    )
    // [lat, lng] pairs along the x axis at 0.125, 0.375, 0.625, 0.875
    expect(pts.map(([, lng]) => lng)).toEqual([0.125, 0.375, 0.625, 0.875])
    expect(pts.every(([lat]) => lat === 0)).toBe(true)
  })

  it('carries spacing across vertices', () => {
    const pts = signPoints(
      [
        [
          [0, 0],
          [0.2, 0],
          [0.2, 1],
        ],
      ],
      0.5,
    )
    expect(pts).toHaveLength(2)
    expect(pts[0][0]).toBeCloseTo(0.05)
    expect(pts[1][0]).toBeCloseTo(0.55)
  })
})

/** Two states side by side, each split into two counties (a 2×2 grid of unit squares). */
function grid() {
  const square = (x: number, y: number, st: string) => ({
    type: 'Feature' as const,
    properties: { st },
    geometry: {
      type: 'Polygon' as const,
      coordinates: [
        [
          [x, y],
          [x + 1, y],
          [x + 1, y + 1],
          [x, y + 1],
          [x, y],
        ],
      ],
    },
  })
  const counties: FeatureCollection = {
    type: 'FeatureCollection',
    features: [square(0, 0, 'A'), square(0, 1, 'A'), square(1, 0, 'B'), square(1, 1, 'B')],
  }
  return topology({ counties, states: counties })
}

describe('countyLines / stateBorders', () => {
  it('draws only lines between counties of the same state', () => {
    const lines = countyLines(grid())
    // The horizontal y=1 line inside each state, not the x=1 state line.
    const xs = lines.coordinates.flat().map(([x]) => x)
    const ys = lines.coordinates.flat().map(([, y]) => y)
    expect(new Set(ys)).toEqual(new Set([1]))
    expect(Math.min(...xs)).toBe(0)
    expect(Math.max(...xs)).toBe(2)
  })

  it('draws borders between different shapes only, not outer edges', () => {
    const topo = grid()
    const borders = stateBorders(topo)
    const pts = borders.coordinates.flat()
    // Every interior edge touches x=1 or y=1; outer edges (x=0/2, y=0/2 all along) are absent.
    expect(pts.every(([x, y]) => x === 1 || y === 1)).toBe(true)
  })
})

describe('chunkLines', () => {
  it('cuts long lines into short pieces that join up with no gaps', () => {
    const line = Array.from({ length: 600 }, (_, i) => [i, 0])
    const pieces = chunkLines({ type: 'MultiLineString', coordinates: [line, [[0, 1], [1, 1]]] }, 256)
      .features.map((f) => f.geometry.coordinates)
    expect(pieces.map((p) => p.length)).toEqual([256, 256, 90, 2])
    expect(pieces[1][0]).toEqual(pieces[0][255])
    expect(pieces[2][0]).toEqual(pieces[1][255])
    expect(pieces[2].at(-1)).toEqual([599, 0])
  })
})
