import 'leaflet/dist/leaflet.css'

import type { GeoJsonObject } from 'geojson'
import type { LatLngBoundsExpression, Layer } from 'leaflet'
import { useEffect, useMemo, useRef, useState } from 'react'
import {
  CircleMarker,
  GeoJSON,
  MapContainer,
  Pane,
  Polyline,
  Tooltip,
  useMap,
} from 'react-leaflet'

import { lineBounds, lineOwners, lineStyle, lineTooltip, UNKNOWN_OWNER } from '../lib/lines'
import { markerStyle } from '../lib/mapStyle'
import { LOW_VOLTAGE_COLOR, VOLTAGE_SCALE } from '../lib/powerGrid'
import { enableSmoothWheelZoom } from '../lib/smoothWheelZoom'
import type { CoordinationPair, LineCollection, LineFeature, Project } from '../types'
import { PowerGridLayer } from './PowerGridLayer'

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
  lines?: LineCollection | null
  linesFailed?: boolean
  onSelectProject: (p: Project) => void
}

export function MapView({
  projects,
  pairs,
  selectedPair,
  colors,
  lines = null,
  linesFailed = false,
  onSelectProject,
}: Props) {
  const [showLines, setShowLines] = useState(true)
  const owners = useMemo(() => (lines ? lineOwners(lines) : []), [lines])
  const projectUtilities = useMemo(
    () => [...new Set(projects.map((p) => p.utility))].sort((a, b) => a.localeCompare(b)),
    [projects],
  )
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
    // With no placed projects yet, frame the reference lines instead.
    return pts.length ? pts : lines ? lineBounds(lines) : null
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [placed.length, lines])

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
        <PowerGridLayer />
        <FitBounds bounds={pairBounds ?? allBounds} />
        {/* Existing lines sit in their own pane under the project markers. */}
        <Pane name="reference-lines" style={{ zIndex: 350 }}>
          {lines && showLines ? (
            <GeoJSON
              key={lines.features.length}
              data={lines as unknown as GeoJsonObject}
              style={(f) => lineStyle(f as unknown as LineFeature, colors)}
              onEachFeature={(f, layer: Layer) =>
                layer.bindTooltip(lineTooltip(f as unknown as LineFeature), { sticky: true })
              }
            />
          ) : null}
        </Pane>
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
        {projectUtilities.map((u) => (
          <span key={u} className="legend-item">
            <span className="swatch" style={{ background: colors[u] ?? '#555' }} />
            {u}
          </span>
        ))}
        <span className="legend-item">
          <span className="swatch swatch-paired" /> in a potential coordination opportunity
        </span>
        <span className="legend-item">
          <span className="swatch swatch-approx" /> approximate location
        </span>
      </div>
      <div className="map-legend grid-legend" aria-label="Power grid legend">
        <span>Grid lines (kV):</span>
        {[...VOLTAGE_SCALE].reverse().map(([kv, c]) => (
          <span key={kv} className="legend-item">
            <span className="swatch swatch-line" style={{ background: c }} />
            {kv}+
          </span>
        ))}
        <span className="legend-item">
          <span className="swatch swatch-line" style={{ background: LOW_VOLTAGE_COLOR }} />
          lower / unknown
        </span>
        <span className="legend-item">
          <span className="swatch swatch-substation" /> substation
        </span>
        <span className="legend-item">
          <span className="swatch swatch-plant" /> power plant
        </span>
      </div>
      {lines && owners.length ? (
        <div className="map-legend lines-legend" aria-label="Existing transmission lines">
          <label className="legend-item">
            <input
              type="checkbox"
              checked={showLines}
              onChange={(e) => setShowLines(e.target.checked)}
            />
            Existing lines (HIFLD)
          </label>
          {showLines
            ? owners.map(({ owner, count }) => (
                <span key={owner ?? UNKNOWN_OWNER} className="legend-item">
                  <span
                    className="swatch swatch-line"
                    style={{ background: owner ? (colors[owner] ?? '#555') : undefined }}
                  />
                  {owner ?? UNKNOWN_OWNER} ({count})
                </span>
              ))
            : null}
        </div>
      ) : null}
      {linesFailed ? (
        <p className="map-note">Existing transmission lines could not be loaded.</p>
      ) : null}
      {projects.length > placed.length ? (
        <p className="map-note">
          {projects.length - placed.length} project(s) have no location yet — see Review.
        </p>
      ) : null}
    </div>
  )
}
