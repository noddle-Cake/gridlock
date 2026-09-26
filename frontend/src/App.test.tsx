import { fireEvent, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { pair, project } from './test/fixtures'

// Leaflet needs a real layout engine; stub the map.
vi.mock('./components/MapView', () => ({ MapView: () => <div data-testid="map" /> }))

import App from './App'

function jsonResponse(body: unknown) {
  return Promise.resolve(new Response(JSON.stringify(body), { status: 200 }))
}

describe('App (Req 10.3, 10.4, 11.1)', () => {
  let fetchMock: ReturnType<typeof vi.fn>

  beforeEach(() => {
    fetchMock = vi.fn((url: string) => {
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

    await userEvent.click(screen.getByText(/Distance apart:/))
    await userEvent.click(screen.getByRole('checkbox', { name: '25–40 km' }))
    await vi.waitFor(() => expect(params().get('bands')).toBe('touching,1.6,8,25'))
    await screen.findByText(/close in both place and time/)
    expect(screen.getByRole('link', { name: 'Export CSV' })).toHaveAttribute(
      'href',
      expect.stringContaining('bands=touching%2C1.6%2C8%2C25'),
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
    await userEvent.type(screen.getByLabelText('Search pairs'), 'nowhere')
    expect(screen.queryByRole('button', { name: /Hanover breakers/ })).toBeNull()
    await userEvent.clear(screen.getByLabelText('Search pairs'))
    await userEvent.type(screen.getByLabelText('Search pairs'), 'westminster')
    expect(screen.getByRole('button', { name: /Hanover breakers/ })).toBeInTheDocument()
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
