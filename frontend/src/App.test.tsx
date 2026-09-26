import { fireEvent, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { pair, project } from './test/fixtures'

// Leaflet and vis-timeline need a real layout engine; stub the views.
vi.mock('./components/MapView', () => ({ MapView: () => <div data-testid="map" /> }))
vi.mock('./components/TimelineView', () => ({ TimelineView: () => <div data-testid="timeline" /> }))

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
        const radius = Number(params.get('radius'))
        return jsonResponse({
          radius,
          pad: Number(params.get('pad')),
          max_overlap_days: 365,
          pairs: radius >= 10 ? [pair()] : [],
        })
      }
      return Promise.reject(new Error(`unexpected ${url}`))
    })
    vi.stubGlobal('fetch', fetchMock)
  })

  afterEach(() => vi.unstubAllGlobals())

  function overlapCalls(): string[] {
    return fetchMock.mock.calls.map((c) => c[0] as string).filter((u) => u.includes('/overlaps'))
  }

  it('re-queries overlaps with the new radius and pad when sliders move', async () => {
    render(<App />)
    await screen.findByText('Hanover breakers')
    expect(overlapCalls().at(-1)).toContain('radius=25&pad=30')

    const radius = screen.getByLabelText('Distance radius (miles)') as HTMLInputElement
    fireEvent.change(radius, { target: { value: '5' } })
    await vi.waitFor(() => expect(overlapCalls().at(-1)).toContain('radius=5&pad=30'))
    await screen.findByText(/No project pairs at these thresholds/)

    const pad = screen.getByLabelText('Date padding (days)') as HTMLInputElement
    fireEvent.change(pad, { target: { value: '120' } })
    await vi.waitFor(() => expect(overlapCalls().at(-1)).toContain('radius=5&pad=120'))
  })

  it('shows the why-flagged panel for a selected pair', async () => {
    render(<App />)
    await userEvent.click(await screen.findByRole('button', { name: /Hanover breakers/ }))
    expect(screen.getByRole('region', { name: 'Why flagged' })).toHaveTextContent('213')
  })
})
