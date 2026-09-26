import fc from 'fast-check'
import { describe, expect, it } from 'vitest'

import { sourceLink } from './sourceLink'

describe('sourceLink', () => {
  // Feature: gridmerge, Property 18: Source link encodes the page
  it('is derived from source_url and encodes source_page', () => {
    fc.assert(
      fc.property(
        fc.webUrl({ withFragments: true, withQueryParameters: true }),
        fc.integer({ min: 1, max: 100_000 }),
        (url, page) => {
          const link = sourceLink(url, page)!
          const base = url.split('#')[0]
          expect(link.startsWith(base)).toBe(true)
          expect(new URL(link).hash).toBe(`#page=${page}`)
          expect(link).toBe(`${base}#page=${page}`)
        },
      ),
      { numRuns: 200 },
    )
  }, 30_000) // 200 URL parses under jsdom can exceed the 5 s default on slow runners

  it('falls back to the bare URL without a valid page, and null without a URL', () => {
    expect(sourceLink('https://x.test/a.pdf#old', null)).toBe('https://x.test/a.pdf')
    expect(sourceLink('https://x.test/a.pdf', 0)).toBe('https://x.test/a.pdf')
    expect(sourceLink(null, 3)).toBeNull()
  })
})
