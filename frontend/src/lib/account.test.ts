import { describe, expect, it } from 'vitest'

import type { CoordinationPair } from '../types'
import { accountCompany, involves, pairPartners, shortName } from './account'

const FPL = 'Florida Power & Light'

describe('accountCompany', () => {
  const utilities = [FPL, 'Duke Energy Florida']

  it('maps a known email domain to its company, ignoring case', () => {
    expect(accountCompany('someone@fpl.com', utilities)).toBe(FPL)
    expect(accountCompany('Someone@FPL.com', utilities)).toBe(FPL)
  })

  it('returns null for guests, unknown domains, or a company with no projects', () => {
    expect(accountCompany(null, utilities)).toBeNull()
    expect(accountCompany('admin', utilities)).toBeNull()
    expect(accountCompany('someone@example.com', utilities)).toBeNull()
    expect(accountCompany('someone@fpl.com', ['Duke Energy Florida'])).toBeNull()
  })
})

describe('pairPartners', () => {
  const pair = (a: string, b: string) =>
    ({ project_a: { utility: a }, project_b: { utility: b } }) as CoordinationPair

  it('ranks the companies FPL shares pairs with, most pairs first', () => {
    const pairs = [
      pair(FPL, 'Tampa Electric'),
      pair('Duke Energy Florida', FPL),
      pair(FPL, 'Duke Energy Florida'),
      pair('JEA', 'Seminole Electric Cooperative'), // not FPL's
    ]
    expect(pairPartners(pairs, FPL)).toEqual(['Duke Energy Florida', 'Tampa Electric'])
  })

  it('counts jointly owned projects and skips pairs within the company', () => {
    const pairs = [pair(`${FPL} / Seminole Electric Cooperative`, 'JEA'), pair(FPL, FPL)]
    expect(pairPartners(pairs, FPL)).toEqual(['JEA'])
  })

  it("tells whether a pair is the company's, alone or jointly owned", () => {
    expect(involves(pair('JEA', FPL), FPL)).toBe(true)
    expect(involves(pair(`Seminole Electric Cooperative / ${FPL}`, 'JEA'), FPL)).toBe(true)
    expect(involves(pair('JEA', 'Tampa Electric'), FPL)).toBe(false)
  })
})

describe('shortName', () => {
  it('uses the name planners say, falling back to the full name', () => {
    expect(shortName(FPL)).toBe('FPL')
    expect(shortName('Tampa Electric')).toBe('Tampa Electric')
  })
})
