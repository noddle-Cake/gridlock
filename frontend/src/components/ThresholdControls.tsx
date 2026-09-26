import { ALL_BANDS, bandSummary, DISTANCE_BANDS, type BandId } from '../lib/distanceBands'
import { DEFAULT_CONFIDENCE_THRESHOLD } from '../lib/review'
import { FilterMenu } from './FilterMenu'

interface Props {
  bands: BandId[]
  confidenceThreshold: number
  onBands: (v: BandId[]) => void
  onConfidenceThreshold: (v: number) => void
}

/** Matching thresholds as filter-bar chips, each opening its own control. */
export function ThresholdControls(props: Props) {
  function toggle(id: BandId, on: boolean) {
    // Keep the canonical band order so queries and the summary are stable.
    props.onBands(
      DISTANCE_BANDS.map((b) => b.id).filter((b) => (b === id ? on : props.bands.includes(b))),
    )
  }

  return (
    <>
      <FilterMenu
        label={
          <span className="chip-text">
            <span className="sr-only">Distance apart: </span>
            {bandSummary(props.bands)}
          </span>
        }
        active={props.bands.length !== ALL_BANDS.length}
      >
        <fieldset className="check-list">
          <legend>Show pairs this far apart</legend>
          {DISTANCE_BANDS.map((b) => (
            <label key={b.id}>
              <input
                type="checkbox"
                checked={props.bands.includes(b.id)}
                onChange={(e) => toggle(b.id, e.target.checked)}
              />
              {b.label}
            </label>
          ))}
        </fieldset>
      </FilterMenu>
      <FilterMenu
        label={<>Review &lt; {props.confidenceThreshold.toFixed(2)}</>}
        active={props.confidenceThreshold !== DEFAULT_CONFIDENCE_THRESHOLD}
      >
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
          <span className="hint">Extractions at or below this go to the Review queue.</span>
        </label>
      </FilterMenu>
    </>
  )
}
