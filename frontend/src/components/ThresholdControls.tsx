import { useEffect, useRef } from 'react'

import { bandSummary, DISTANCE_BANDS, type BandId } from '../lib/distanceBands'

interface Props {
  bands: BandId[]
  pad: number
  confidenceThreshold: number
  onBands: (v: BandId[]) => void
  onPad: (v: number) => void
  onConfidenceThreshold: (v: number) => void
}

export function ThresholdControls(props: Props) {
  return (
    <section className="controls" aria-label="Matching thresholds">
      <DistanceBandPicker bands={props.bands} onBands={props.onBands} />
      <label className="slider">
        <span className="slider-label">
          Date padding <output>±{props.pad} days</output>
        </span>
        <input
          type="range"
          min={0}
          max={365}
          step={5}
          value={props.pad}
          aria-label="Date padding (days)"
          onChange={(e) => props.onPad(Number(e.target.value))}
        />
      </label>
      <label className="slider">
        <span className="slider-label">
          Review below confidence <output>{props.confidenceThreshold.toFixed(2)}</output>
        </span>
        <input
          type="range"
          min={0}
          max={1}
          step={0.05}
          value={props.confidenceThreshold}
          aria-label="Confidence threshold"
          onChange={(e) => props.onConfidenceThreshold(Number(e.target.value))}
        />
      </label>
    </section>
  )
}

function DistanceBandPicker({
  bands,
  onBands,
}: {
  bands: BandId[]
  onBands: (v: BandId[]) => void
}) {
  const ref = useRef<HTMLDetailsElement>(null)

  // Close on a click outside or Escape, like a native select.
  useEffect(() => {
    function onPointer(e: PointerEvent) {
      if (ref.current?.open && !ref.current.contains(e.target as Node)) ref.current.open = false
    }
    function onKey(e: KeyboardEvent) {
      if (e.key === 'Escape' && ref.current?.open) {
        ref.current.open = false
        ref.current.querySelector('summary')?.focus()
      }
    }
    document.addEventListener('pointerdown', onPointer)
    document.addEventListener('keydown', onKey)
    return () => {
      document.removeEventListener('pointerdown', onPointer)
      document.removeEventListener('keydown', onKey)
    }
  }, [])

  function toggle(id: BandId, on: boolean) {
    // Keep the canonical band order so queries and the summary are stable.
    onBands(DISTANCE_BANDS.map((b) => b.id).filter((b) => (b === id ? on : bands.includes(b))))
  }

  return (
    <div className="slider">
      <span className="slider-label" aria-hidden="true">
        Distance apart
      </span>
      <details ref={ref} className="band-picker">
        <summary>
          <span className="sr-only">Distance apart: </span>
          {bandSummary(bands)}
        </summary>
        <fieldset>
          <legend className="sr-only">Show pairs this far apart</legend>
          {DISTANCE_BANDS.map((b) => (
            <label key={b.id} className="band-option">
              <input
                type="checkbox"
                checked={bands.includes(b.id)}
                onChange={(e) => toggle(b.id, e.target.checked)}
              />
              {b.label}
            </label>
          ))}
        </fieldset>
      </details>
    </div>
  )
}
