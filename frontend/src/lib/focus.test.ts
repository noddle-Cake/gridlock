import { describe, expect, it } from 'vitest'

import { focusHidden } from './focus'

describe('focusHidden', () => {
  it('hides everything but DESC and Georgia Power when both are loaded', () => {
    const all = ['Dominion Energy South Carolina', 'Duke Energy Carolinas', 'Georgia Power', 'TVA']
    expect(focusHidden(all)).toEqual(new Set(['Duke Energy Carolinas', 'TVA']))
  })

  it('does nothing unless every focus utility is loaded', () => {
    expect(focusHidden(['Georgia Power', 'TVA'])).toBeNull()
  })
})
