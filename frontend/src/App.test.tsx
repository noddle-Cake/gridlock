import { fireEvent, render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { pair, project } from './test/fixtures'
import type { SearchResponse } from './types'
import type { MapFocus } from './components/MapView'

// Leaflet needs a real layout engine; stub the map.
vi.mock('./components/MapView', () => ({
  MapView: ({ focus }: { focus?: MapFocus | null }) => (
    <div data-testid="map" data-focus={JSON.stringify(focus?.bounds ?? null)} />
  ),
}))

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
          planning_from: '2026-09-26',
          min_overlap_days: 30,
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

    await userEvent.click(screen.getByText(/Opportunity type:/))
    await userEvent.click(screen.getByRole('checkbox', { name: 'Shared crews & equipment' }))
    await vi.waitFor(() => expect(params().get('bands')).toBe('touching,1.6,8'))
    await screen.findByText(/close in both place and time/)
    expect(screen.getByRole('link', { name: 'Export CSV' })).toHaveAttribute(
      'href',
      expect.stringContaining('bands=touching%2C1.6%2C8'),
    )
  })

  it('states the timing rules and how long each pair builds together', async () => {
    render(<App />)
    const card = await screen.findByRole('button', { name: /Hanover breakers/ })
    expect(screen.getByTestId('match-rules')).toHaveTextContent(
      'Future work only (in service from Sep 26, 2026), within 40 km, and building at the ' +
        'same time for at least 30 days.',
    )
    // The fixture pair shares Apr 1 - Oct 30, 2026 (213 days).
    expect(card).toHaveTextContent('7 months building together')
    expect(card).toHaveTextContent('Both building Apr 2026 – Oct 2026 · 58% of their build time')
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
    expect(screen.getByTestId('map')).toHaveAttribute(
      'data-focus', JSON.stringify([[39.58, -77], [39.58, -77]]),
    )
  })

  it('locates 33034 automatically even when no planned projects are nearby', async () => {
    const inner = fetchMock.getMockImplementation() as (url: string, init?: RequestInit) => unknown
    fetchMock.mockImplementation((url: string, init?: RequestInit) =>
      url.startsWith('/api/search?q=33034')
        ? jsonResponse({
            ...zipSearch,
            query: '33034',
            interpretation: {
              ...zipSearch.interpretation, zip: '33034',
              zip_label: 'ZIP 33034', radius_miles: 100,
            },
            locations: [{ kind: 'zip', code: '33034', label: 'ZIP 33034 · 100 mi', project_count: 0 }],
            projects: [], project_ids: [], total: 0,
            bounds: [25.4722, -80.7733, 25.4722, -80.7733],
          })
        : inner(url, init),
    )
    render(<App />)
    await screen.findByRole('button', { name: /Hanover breakers/ })
    await userEvent.type(screen.getByLabelText('Search GridMerge'), '33034')
    expect(await screen.findByText('No matching planned projects within 100 mi of ZIP 33034.'))
      .toBeInTheDocument()
    expect(screen.getByTestId('map')).toHaveAttribute(
      'data-focus', JSON.stringify([[25.4722, -80.7733], [25.4722, -80.7733]]),
    )
  })

  it('reports a failed ZIP lookup and clears the error when another lookup succeeds', async () => {
    render(<App />)
    await screen.findByRole('button', { name: /Hanover breakers/ })
    await userEvent.type(screen.getByLabelText('Search GridMerge'), '33034{Enter}')
    expect(await screen.findByRole('alert')).toHaveTextContent('Search is unavailable')
    expect(screen.getByTestId('map')).toHaveAttribute('data-focus', 'null')
    await userEvent.clear(screen.getByLabelText('Search GridMerge'))
    await userEvent.type(screen.getByLabelText('Search GridMerge'), '21157')
    await screen.findByRole('option', { name: /ZIP 21157 · near Carroll County/ })
    expect(screen.queryByRole('alert')).toBeNull()
    expect(screen.getByTestId('map')).toHaveAttribute(
      'data-focus', JSON.stringify([[39.58, -77], [39.58, -77]]),
    )
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

  /** Hold responses to `prefix` until the returned function releases them with `body`. */
  function holdResponses(prefix: string) {
    const inner = fetchMock.getMockImplementation() as (u: string, i?: RequestInit) => unknown
    let release: (body: unknown) => void = () => {}
    const held = new Promise<unknown>((resolve) => (release = resolve))
    fetchMock.mockImplementation((url: string, init?: RequestInit) =>
      url.startsWith(prefix) ? held.then((body) => new Response(JSON.stringify(body))) : inner(url, init),
    )
    return (body: unknown) => release(body)
  }

  it('keeps drafting a brief after leaving the pair and says when it is ready', async () => {
    const finish = holdResponses('/api/overlaps/1-2/brief')
    document.title = 'GridMerge'
    render(<App />)
    await userEvent.click(await screen.findByRole('button', { name: /Hanover breakers/ }))
    await userEvent.click(screen.getByRole('button', { name: 'Generate brief' }))
    expect(screen.getByRole('button', { name: 'Drafting…' })).toBeDisabled()
    const tray = screen.getByRole('status', { name: 'AI activity' })
    expect(tray).toHaveTextContent('Drafting brief')

    // Leave the pair; the draft carries on, and the pair still knows when revisited.
    await userEvent.click(screen.getByRole('button', { name: '← Back to list' }))
    finish({ pair_id: '1-2', text: 'Coordinate the outages.', source: 'llm', stale: false })
    const ready = await within(tray).findByRole('button', { name: /^Brief ready/ })
    await vi.waitFor(() => expect(document.title).toBe('(1) GridMerge'))

    await userEvent.click(ready)
    expect(await screen.findByTestId('brief-text')).toHaveTextContent('Coordinate the outages.')
    expect(within(tray).queryByRole('button', { name: /^Brief ready/ })).toBeNull()
    await vi.waitFor(() => expect(document.title).toBe('GridMerge'))
  })

  it('keeps answering after the Ask panel is closed and opens the answer from the header', async () => {
    const finish = holdResponses('/api/ask')
    render(<App />)
    await screen.findByRole('button', { name: /Hanover breakers/ })
    await userEvent.type(screen.getByLabelText('Search GridMerge'), 'Anything near Hanover?')
    await userEvent.click(screen.getByRole('button', { name: 'Ask GridMerge' }))
    await userEvent.click(await screen.findByRole('button', { name: 'Close answer' }))
    expect(screen.queryByRole('region', { name: 'Ask GridMerge' })).toBeNull()

    const tray = screen.getByRole('status', { name: 'AI activity' })
    expect(tray).toHaveTextContent('Answering')
    finish({ question: 'Anything near Hanover?', answer: 'Yes: Hanover breakers [#1].',
      projects: [project()], tool_calls: [] })
    await userEvent.click(await within(tray).findByRole('button', { name: /^Answer ready/ }))
    const panel = await screen.findByRole('region', { name: 'Ask GridMerge' })
    expect(panel).toHaveTextContent('Yes: Hanover breakers')
  })

  it('lifts the utility focus when a search is applied', async () => {
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
    await screen.findByRole('button', { name: /Hanover breakers/ })
    await userEvent.click(screen.getByText('All utilities'))
    await userEvent.click(screen.getByRole('button', { name: 'Only Dominion SC ↔ Georgia Power' }))
    expect(await screen.findByText('Dominion SC ↔ Georgia Power')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /Hanover breakers/ })).toBeNull()

    await userEvent.type(screen.getByLabelText('Search GridMerge'), 'westminster{Enter}')
    expect(await screen.findByRole('button', { name: /Hanover breakers/ })).toBeInTheDocument()
  })

  it('opens on every utility; "Only Dominion SC ↔ Georgia Power" scopes the view', async () => {
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
          ? jsonResponse({
              radius: 25,
              planning_from: '2026-09-26',
              min_overlap_days: 30,
              pairs: [pair()],
            })
          : jsonResponse({ type: 'FeatureCollection', features: [] }),
    )
    render(<App />)
    // Every utility is shown at first, and the pair query covers them all.
    expect(await screen.findByRole('button', { name: /Hanover breakers/ })).toBeInTheDocument()
    expect(screen.getByText('All utilities')).toBeInTheDocument()
    expect(new URL(overlapCalls()[0], 'http://x').searchParams.has('utility')).toBe(false)

    await userEvent.click(screen.getByText('All utilities'))
    await userEvent.click(screen.getByRole('button', { name: 'Only Dominion SC ↔ Georgia Power' }))
    expect(await screen.findByText('Dominion SC ↔ Georgia Power')).toBeInTheDocument()
    // The Keystone/Chesapeake fixture pair is hidden by the focus ...
    expect(screen.queryByRole('button', { name: /Hanover breakers/ })).toBeNull()
    // ... and only the two utilities' pairs are asked for.
    await vi.waitFor(() =>
      expect(new URL(overlapCalls().at(-1)!, 'http://x').searchParams.getAll('utility')).toEqual([
        'Dominion Energy South Carolina',
        'Georgia Power',
      ]),
    )
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
