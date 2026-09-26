import 'leaflet/dist/leaflet.css'

import type { LatLngBoundsExpression } from 'leaflet'
import { useEffect, useMemo, useRef } from 'react'
import { CircleMarker, MapContainer, Polyline, TileLayer, Tooltip, useMap } from 'react-leaflet'

import { markerStyle } from '../lib/mapStyle'
import { enableSmoothWheelZoom } from '../lib/smoothWheelZoom'
import type { CoordinationPair, Project } from '../types'

function FitBounds({ bounds }: { bounds: LatLngBoundsExpression | null }) {
  const map = useMap()
  const fitted = useRef(false)
  useEffect(() => {
    if (!bounds) return
    const opts = { padding: [40, 40] as [number, number], maxZoom: 11 }
    // Snap on first load; glide between views after that.
    if (fitted.current) map.flyToBounds(bounds, { ...opts, duration: 0.8 })
    else map.fitBounds(bounds, { ...opts, animate: false })
    fitted.current = true
  }, [map, bounds])
  return null
}

function SmoothWheelZoom() {
  const map = useMap()
  useEffect(() => enableSmoothWheelZoom(map), [map])
  return null
}

interface Props {
  projects: Project[]
  pairs: CoordinationPair[]
  selectedPair: CoordinationPair | null
  colors: Record<string, string>
  onSelectProject: (p: Project) => void
}

export function MapView({ projects, pairs, selectedPair, colors, onSelectProject }: Props) {
  const placed = projects.filter((p) => p.lat != null && p.lng != null)
  const pairedIds = useMemo(
    () => new Set(pairs.flatMap((p) => [p.project_a.id, p.project_b.id])),
    [pairs],
  )
  const selectedIds = new Set(
    selectedPair ? [selectedPair.project_a.id, selectedPair.project_b.id] : [],
  )

  const allBounds = useMemo<LatLngBoundsExpression | null>(() => {
    const pts = placed.map((p) => [p.lat!, p.lng!] as [number, number])
    return pts.length ? pts : null
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [placed.length])

  // Keyed on coordinates, not the pair object, so a data refresh doesn't re-trigger the fly.
  const a = selectedPair?.project_a
  const b = selectedPair?.project_b
  const pairBounds = useMemo<LatLngBoundsExpression | null>(() => {
    if (a?.lat == null || a.lng == null || b?.lat == null || b.lng == null) return null
    return [
      [a.lat, a.lng],
      [b.lat, b.lng],
    ]
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [a?.lat, a?.lng, b?.lat, b?.lng])

  // Draw unselected, then paired, then selected so highlighted markers sit on top.
  const ordered = [...placed].sort((a, b) => rank(a) - rank(b))
  function rank(p: Project) {
    return selectedIds.has(p.id) ? 2 : pairedIds.has(p.id) ? 1 : 0
  }

  return (
    <div className="map-wrap">
      <MapContainer
        center={[39.8, -77.1]}
        zoom={9}
        zoomSnap={0}
        scrollWheelZoom={false}
        className="map"
      >
        <SmoothWheelZoom />
        <TileLayer
          attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'
          url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
        />
        <FitBounds bounds={pairBounds ?? allBounds} />
        {pairs.map((pair) => {
          const { project_a: a, project_b: b } = pair
          if (a.lat == null || b.lat == null) return null
          const selected = selectedPair?.id === pair.id
          return (
            <Polyline
              key={pair.id}
              positions={[
                [a.lat, a.lng!],
                [b.lat, b.lng!],
              ]}
              pathOptions={{
                color: selected ? '#111' : '#f08c00',
                weight: selected ? 3 : 1.5,
                opacity: selected ? 0.9 : 0.45,
                dashArray: selected ? undefined : '3 5',
              }}
            />
          )
        })}
        {ordered.map((p) => {
          const style = markerStyle(p, colors[p.utility] ?? '#555', {
            paired: pairedIds.has(p.id),
            selected: selectedIds.has(p.id),
          })
          return (
            <CircleMarker
              key={p.id}
              center={[p.lat!, p.lng!]}
              radius={style.radius}
              pathOptions={style}
              eventHandlers={{ click: () => onSelectProject(p) }}
            >
              <Tooltip>
                <strong>{p.name || 'Unnamed project'}</strong>
                <br />
                {p.utility} · {p.type ?? 'type unknown'}
                {p.voltage_kv ? ` · ${p.voltage_kv} kV` : ''}
                {p.approximate ? (
                  <>
                    <br />
                    <em>Approximate location (county center)</em>
                  </>
                ) : null}
              </Tooltip>
            </CircleMarker>
          )
        })}
      </MapContainer>
      <div className="map-legend" aria-label="Map legend">
        {Object.entries(colors).map(([u, c]) => (
          <span key={u} className="legend-item">
            <span className="swatch" style={{ background: c }} />
            {u}
          </span>
        ))}
        <span className="legend-item">
          <span className="swatch swatch-paired" /> in a flagged pair
        </span>
        <span className="legend-item">
          <span className="swatch swatch-approx" /> approximate location
        </span>
      </div>
      {projects.length > placed.length ? (
        <p className="map-note">
          {projects.length - placed.length} project(s) have no location yet — see Review.
        </p>
      ) : null}
    </div>
  )
}
