import { describe, expect, it } from 'vitest'

import { wheelZoomDelta } from './smoothWheelZoom'

describe('wheelZoomDelta', () => {
  it('tracks a trackpad pinch 1:1 (doubling scale = one zoom level)', () => {
    const deltaY = -100 * Math.log(2) // Chromium's ctrl+wheel encoding of a 2x pinch-out
    expect(wheelZoomDelta({ deltaY, deltaMode: 0, ctrlKey: true })).toBeCloseTo(1)
  })

  it('maps a mouse-wheel notch to about one level, zooming out on scroll down', () => {
    expect(wheelZoomDelta({ deltaY: 100, deltaMode: 0, ctrlKey: false })).toBeCloseTo(-1)
    expect(wheelZoomDelta({ deltaY: -3, deltaMode: 1, ctrlKey: false })).toBeCloseTo(0.48)
  })

  it('clamps runaway deltas', () => {
    expect(wheelZoomDelta({ deltaY: -5000, deltaMode: 0, ctrlKey: false })).toBe(2)
    expect(wheelZoomDelta({ deltaY: 1, deltaMode: 2, ctrlKey: true })).toBe(-2)
  })
})
