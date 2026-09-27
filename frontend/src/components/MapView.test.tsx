import { fireEvent, render, screen } from '@testing-library/react'
import type { ReactNode } from 'react'
import { describe, expect, it, vi } from 'vitest'

import type { ZoomStyle } from '../lib/liveCanvas'

import { pair, project } from '../test/fixtures'

const view = vi.hoisted(() => ({ zoom: 9, zoomStyles: [] as ZoomStyle[] }))

// Keep MapView's state logic, replacing Leaflet's browser-only drawing surface.
vi.mock('react-leaflet', () => {
  const map = {
    getZoom: () => view.zoom,
    getContainer: () => document.createElement('div'),
    getSize: () => ({ x: 1000 }),
    getBounds: () => ({}),
    fitBounds: vi.fn(),
    on: vi.fn(),
    off: vi.fn(),
  }
  return {
    MapContainer: ({ children }: { children: ReactNode }) => <div>{children}</div>,
    CircleMarker: ({ radius, pathOptions, eventHandlers }: {
      radius: number
      pathOptions: { fill?: boolean; zoomStyle?: ZoomStyle }
      eventHandlers?: { click?: () => void }
    }) => {
      if (pathOptions.zoomStyle) view.zoomStyles.push(pathOptions.zoomStyle)
      return (
        <button
          data-testid={pathOptions.fill === false ? 'touching-ring' : 'project-circle'}
          data-radius={radius}
          onClick={eventHandlers?.click}
        />
      )
    },
    Polyline: ({ eventHandlers }: { eventHandlers?: { click?: () => void } }) => (
      <button data-testid="pair-guide" onClick={eventHandlers?.click} />
    ),
    ScaleControl: () => null,
    Tooltip: () => null,
    useMap: () => map,
  }
})
vi.mock('./BaseMap', () => ({ BaseMap: () => null }))
vi.mock('./PowerGridLayer', () => ({ PowerGridLayer: () => null }))
vi.mock('../lib/smoothWheelZoom', () => ({ enableSmoothWheelZoom: () => () => {} }))

import { MapView } from './MapView'

describe('map coordination markers across zoom levels', () => {
  it.each([9, 3])('keeps circles and guides visible and clickable from zoom %s', (initialZoom) => {
    view.zoom = initialZoom
    view.zoomStyles = []
    const separated = pair()
    const touching = pair({
      id: '3-4',
      project_a: project({ id: 3, lat: 40, lng: -77 }),
      project_b: project({ id: 4, lat: 40, lng: -77 }),
      miles: 0,
    })
    const onSelectPair = vi.fn()
    const onSelectProject = vi.fn()
    render(
      <MapView
        projects={[
          project(separated.project_a), project(separated.project_b),
          project(touching.project_a), project(touching.project_b),
        ]}
        pairs={[separated, touching]}
        selectedPair={null}
        colorOf={() => '#2a78d6'}
        colorBy="utility"
        onColorBy={vi.fn()}
        legend={[]}
        onSelectProject={onSelectProject}
        onSelectPair={onSelectPair}
      />,
    )
    const guide = screen.getByTestId('pair-guide')
    const ring = screen.getByTestId('touching-ring')
    const circles = screen.getAllByTestId('project-circle')

    for (const circle of circles) {
      expect(Number(circle.dataset.radius)).toBeGreaterThanOrEqual(2)
    }
    // The canvas sizes each dot for the zoom as it draws (no re-render per zoom).
    expect(view.zoomStyles).toHaveLength(circles.length)
    for (const zoomStyle of view.zoomStyles) {
      for (const zoom of [9, 6, 5.99, 5, 3]) {
        expect(zoomStyle(zoom).radius).toBeGreaterThanOrEqual(2)
      }
    }
    fireEvent.click(guide)
    expect(onSelectPair).toHaveBeenLastCalledWith(separated)
    fireEvent.click(ring)
    expect(onSelectPair).toHaveBeenLastCalledWith(touching)
    fireEvent.click(circles[0])
    expect(onSelectProject).toHaveBeenLastCalledWith(separated.project_a)
  })
})
