import { describe, expect, it } from 'vitest'

import { legendStartsOpen } from './legendLayout'

describe('legendStartsOpen', () => {
  it('opens on a desktop-sized map', () => {
    expect(legendStartsOpen(811, 792)).toBe(true)
  })

  it('starts collapsed on the short stacked tablet map', () => {
    expect(legendStartsOpen(860, 495)).toBe(false)
  })

  it('starts collapsed on a narrow split-layout map', () => {
    expect(legendStartsOpen(420, 790)).toBe(false)
  })

  it('keeps the default open card when the map has not been measured', () => {
    expect(legendStartsOpen(0, 0)).toBe(true)
  })
})
