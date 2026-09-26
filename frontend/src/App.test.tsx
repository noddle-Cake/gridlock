import { fireEvent, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { pair, project } from './test/fixtures'
import type { SearchResponse } from './types'

// Leaflet needs a real layout engine; stub the map.
vi.mock('./components/MapView', () => ({ MapView: () => <div data-testid="map" /> }))

import App from './App'

function jsonResponse(body: unknown) {
  return Promise.resolve(new Response(JSON.stringify(body), { status: 200 }))
}

// GET /search for a ZIP near Westminster: the server matches project 2 by distance, which
// local text matching could never do.
const zipSearch: SearchResponse = {
  query: '21157',
  interpretation: {
    zip: '21157', zip_found: true, zip_label: 'ZIP 21157 · near Carroll County, MD',
    radius_miles: 25, states: [], utilities: [], types: [], terms: [], fuzzy: false,
  },
  companies: [],
  locations: [
    { kind: 'zip', code: '21157', label: 'ZIP 21157 · near Carroll County, MD · 25 mi', project_count: 1 },
  ],
  projects: [
    {
      ...project({ id: 2, utility: 'Chesapeake Power', name: 'Westminster breakers', lat: 39.58, lng: -77 }),
      miles: 1.2,
    },
  ],
  project_ids: [2],
  total: 1,
  bounds: [39.58, -77.0, 39.58, -77.0],
  suggest_ai: false,
}

describe('App (Req 10.3, 10.4, 11.1)', () => {
  let fetchMock: ReturnType<typeof vi.fn>

  beforeEach(() => {
    history.replaceState(null, '', '/') // an open pair lives in the hash; start from the list
    fetchMock = vi.fn((url: string, init?: RequestInit) => {
      if (url.startsWith('/api/search')) {
        const q = new URL(url, 'http://x').searchParams.get('q')
        return q === '21157' ? jsonResponse(zipSearch) : Promise.reject(new Error('offline'))
      }
      if (url.startsWith('/api/ask')) {
        const { question } = JSON.parse(String(init?.body))
        if (question === 'no key') {
          return Promise.resolve(
            new Response(
              JSON.stringify({ error: { code: 'ai_unavailable', message: 'AI answers are off.' } }),
              { status: 503 },
            ),
          )
        }
        return jsonResponse({
          question,
          answer: 'One pair crosses the state line:\n- **Keystone Electric** [#1] near Hanover',
          projects: [project()],
          tool_calls: [{ name: 'search_gridmerge', arguments: { state: 'PA' }, summary: '1 projects' }],
        })
      }
      if (url.startsWith('/api/projects')) return jsonResponse([project(), pair().project_b])
      if (url.startsWith('/api/overlaps')) {
        const params = new URL(url, 'http://x').searchParams
        // The fixture pair is ~25.1 km apart: the 25-40 km band.
        const bands = params.get('bands')?.split(',') ?? []
        return jsonResponse({
          radius: Number(params.get('radius')),
          pairs: bands.includes('40') ? [pair()] : [],
        })
      }
      if (url.startsWith('/api/lines')) return jsonResponse({ type: 'FeatureCollection', features: [] })
      return Promise.reject(new Error(`unexpected ${url}`))
    })
    vi.stubGlobal('fetch', fetchMock)
  })

  afterEach(() => vi.unstubAllGlobals())

  function overlapCalls(): string[] {
    return fetchMock.mock.calls.map((c) => c[0] as string).filter((u) => u.includes('/overlaps'))
  }

  it('re-queries overlaps with the ticked bands', async () => {
    render(<App />)
    await screen.findByText('Hanover breakers')
    const params = () => new URL(overlapCalls().at(-1)!, 'http://x').searchParams
    expect(params().get('bands')).toBe('touching,1.6,8,25,40')
    expect(Number(params().get('radius'))).toBeCloseTo(24.855, 3) // 40 km
    expect(params().has('pad')).toBe(false)

    await userEvent.click(screen.getByText(/Distance apart:/))
    await userEvent.click(screen.getByRole('checkbox', { name: '25–40 km' }))
    await vi.waitFor(() => expect(params().get('bands')).toBe('touching,1.6,8,25'))
    await screen.findByText(/No project pairs at these thresholds/)
    expect(screen.getByRole('link', { name: 'Export CSV' })).toHaveAttribute(
      'href',
      expect.stringContaining('bands=touching%2C1.6%2C8%2C25'),
    )
  })

  it('no longer shows the timeline under the map', async () => {
    render(<App />)
    await screen.findByText('Hanover breakers')
    expect(document.querySelector('.timeline')).toBeNull()
  })

  it('shows the why-flagged panel for a selected pair', async () => {
    render(<App />)
    await userEvent.click(await screen.findByRole('button', { name: /Hanover breakers/ }))
    expect(screen.getByRole('region', { name: 'Why flagged' })).toHaveTextContent('213')
    expect(screen.getByText('1 of 1')).toBeInTheDocument()

    await userEvent.click(screen.getByRole('button', { name: /Back to list/ }))
    expect(screen.queryByRole('region', { name: 'Why flagged' })).toBeNull()
    expect(screen.getByRole('region', { name: 'Potential coordination opportunities' })).toBeInTheDocument()
  })

  it('opens a pair at its top and returns to the same place in the list', async () => {
    render(<App />)
    const card = await screen.findByRole('button', { name: /Hanover breakers/ })
    const panel = screen.getByRole('complementary', { name: 'Pairs' })
    panel.scrollTop = 120
    fireEvent.scroll(panel)
    await userEvent.click(card)
    expect(panel.scrollTop).toBe(0)
    panel.scrollTop = 400 // read far down the detail
    await userEvent.click(screen.getByRole('button', { name: /Back to list/ }))
    expect(panel.scrollTop).toBe(120)
  })

  it('filters the list by search text', async () => {
    render(<App />)
    await screen.findByRole('button', { name: /Hanover breakers/ })
    await userEvent.type(screen.getByLabelText('Search GridMerge'), 'nowhere')
    expect(screen.queryByRole('button', { name: /Hanover breakers/ })).toBeNull()
    await userEvent.clear(screen.getByLabelText('Search GridMerge'))
    await userEvent.type(screen.getByLabelText('Search GridMerge'), 'westminster')
    expect(screen.getByRole('button', { name: /Hanover breakers/ })).toBeInTheDocument()
  })

  it('filters by the server matches for a ZIP code and suggests the place', async () => {
    render(<App />)
    await screen.findByRole('button', { name: /Hanover breakers/ })
    await userEvent.type(screen.getByLabelText('Search GridMerge'), '21157')
    // Locally "21157" matches nothing; once /search answers, its ids drive the list.
    expect(await screen.findByRole('option', { name: /ZIP 21157 · near Carroll County/ }))
      .toHaveTextContent('1 project')
    expect(screen.getByRole('option', { name: /Westminster breakers/ })).toHaveTextContent('1.2 mi')
    expect(screen.getByRole('button', { name: /Hanover breakers/ })).toBeInTheDocument()
  })

  it('answers with Ask GridMerge and links cited projects to their pair', async () => {
    render(<App />)
    await screen.findByRole('button', { name: /Hanover breakers/ })
    await userEvent.type(screen.getByLabelText('Search GridMerge'), 'Which pairs cross into MD?')
    await userEvent.click(screen.getByRole('button', { name: 'Ask GridMerge' }))

    const panel = await screen.findByRole('region', { name: 'Ask GridMerge' })
    await vi.waitFor(() => expect(panel).toHaveTextContent('One pair crosses the state line'))
    expect(panel.querySelector('li strong')).toHaveTextContent('Keystone Electric')
    expect(panel).toHaveTextContent(/Searched projects \(state: PA\) → 1 projects/)
    const [body] = fetchMock.mock.calls.filter((c) => String(c[0]).startsWith('/api/ask'))
    expect(JSON.parse(String(body[1].body))).toEqual({ question: 'Which pairs cross into MD?' })

    await userEvent.click(screen.getByRole('button', { name: '#1' }))
    expect(screen.getByRole('region', { name: 'Why flagged' })).toBeInTheDocument()
  })

  it('explains when AI answers are unavailable', async () => {
    render(<App />)
    await screen.findByRole('button', { name: /Hanover breakers/ })
    await userEvent.type(screen.getByLabelText('Search GridMerge'), 'no key')
    await userEvent.click(screen.getByRole('button', { name: 'Ask GridMerge' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('AI answers are off.')
    await userEvent.click(screen.getByRole('button', { name: 'Close answer' }))
    expect(screen.queryByRole('region', { name: 'Ask GridMerge' })).toBeNull()
  })

  it('lifts the opening utility focus when a search is applied', async () => {
    const desc = project({ id: 7, utility: 'Dominion Energy South Carolina', name: 'Jasper – Okatie' })
    const gpc = project({ id: 8, utility: 'Georgia Power', name: 'McIntosh reactors' })
    const inner = fetchMock.getMockImplementation() as (u: string, i?: RequestInit) => unknown
    fetchMock.mockImplementation((url: string, init?: RequestInit) =>
      url.startsWith('/api/projects')
        ? jsonResponse([project(), pair().project_b, desc, gpc])
        : url.startsWith('/api/search')
          ? jsonResponse({ ...zipSearch, query: 'westminster', project_ids: [2] })
          : inner(url, init),
    )
    render(<App />)
    expect(await screen.findByText('Dominion SC ↔ Georgia Power')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /Hanover breakers/ })).toBeNull()

    await userEvent.type(screen.getByLabelText('Search GridMerge'), 'westminster{Enter}')
    expect(await screen.findByRole('button', { name: /Hanover breakers/ })).toBeInTheDocument()
  })

  it('opens on Dominion SC ↔ Georgia Power when both are loaded', async () => {
    // Low confidence, so both would be listed in Review if it ignored the focus.
    const desc = project({
      id: 7,
      utility: 'Dominion Energy South Carolina',
      name: 'Jasper – Okatie',
      confidence: 0.5,
    })
    const gpc = project({ id: 8, utility: 'Georgia Power', name: 'McIntosh reactors' })
    fetchMock.mockImplementation((url: string) =>
      url.startsWith('/api/projects')
        ? jsonResponse([project({ confidence: 0.4 }), desc, gpc])
        : url.startsWith('/api/overlaps')
          ? jsonResponse({ radius: 25, pad: 365, max_overlap_days: 365, pairs: [pair()] })
          : jsonResponse({ type: 'FeatureCollection', features: [] }),
    )
    render(<App />)
    expect(await screen.findByText('Dominion SC ↔ Georgia Power')).toBeInTheDocument()
    // The Keystone/Chesapeake fixture pair is hidden by the focus.
    expect(screen.queryByRole('button', { name: /Hanover breakers/ })).toBeNull()

    // Only the two utilities' pairs are asked for, from the very first request.
    await vi.waitFor(() => expect(overlapCalls().length).toBeGreaterThan(0))
    for (const url of overlapCalls()) {
      expect(new URL(url, 'http://x').searchParams.getAll('utility')).toEqual([
        'Dominion Energy South Carolina',
        'Georgia Power',
      ])
    }
    expect(screen.getByRole('link', { name: 'Export CSV' })).toHaveAttribute(
      'href',
      expect.stringContaining('utility=Georgia+Power'),
    )

    // Review follows the focus too: the Keystone project is out of scope.
    await userEvent.click(screen.getByRole('button', { name: /Review/ }))
    expect(screen.queryByText('Hanover breakers')).toBeNull()
    expect(screen.getByText('Jasper – Okatie')).toBeInTheDocument()
  })
})
