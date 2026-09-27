import { describe, expect, it } from 'vitest'

import { homePoints, inLower48, type LatLng } from './homeView'

const AUGUSTA: LatLng = [33.47, -81.97]
const SEATTLE: LatLng = [47.61, -122.33]
const KEY_WEST: LatLng = [24.56, -81.78]
const EASTPORT_ME: LatLng = [44.9, -66.99]
const KETCHIKAN: LatLng = [55.34, -131.64]
const HONOLULU: LatLng = [21.31, -157.86]
const SAN_JUAN: LatLng = [18.47, -66.11]

describe('inLower48', () => {
  it('keeps the mainland corners and drops Alaska, Hawaii and Puerto Rico', () => {
    for (const p of [AUGUSTA, SEATTLE, KEY_WEST, EASTPORT_ME]) expect(inLower48(p)).toBe(true)
    for (const p of [KETCHIKAN, HONOLULU, SAN_JUAN]) expect(inLower48(p)).toBe(false)
  })
})

describe('homePoints', () => {
  it('fits only the lower 48 when any projects are there', () => {
    expect(homePoints([AUGUSTA, KETCHIKAN, SEATTLE, HONOLULU, SAN_JUAN])).toEqual([AUGUSTA, SEATTLE])
  })

  it('falls back to every point when none are in the lower 48', () => {
    expect(homePoints([KETCHIKAN, HONOLULU])).toEqual([KETCHIKAN, HONOLULU])
  })

  it('is null with nothing to fit', () => {
    expect(homePoints([])).toBeNull()
  })
})
