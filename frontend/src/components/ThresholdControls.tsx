import { DEFAULT_CONFIDENCE_THRESHOLD } from '../lib/review'
import { FilterMenu } from './FilterMenu'

export const DEFAULT_RADIUS = 25
export const DEFAULT_PAD = 30

interface Props {
  radius: number
  pad: number
  confidenceThreshold: number
  onRadius: (v: number) => void
  onPad: (v: number) => void
  onConfidenceThreshold: (v: number) => void
}

/** Matching thresholds as filter-bar chips, each opening its own slider. */
export function ThresholdControls(props: Props) {
  return (
    <>
      <FilterMenu
        label={<>Within {props.radius} mi</>}
        active={props.radius !== DEFAULT_RADIUS}
      >
        <label className="slider">
          <span className="slider-label">
            Distance radius <output>{props.radius} mi</output>
          </span>
          <input
            type="range"
            min={0}
            max={100}
            step={1}
            value={props.radius}
            aria-label="Distance radius (miles)"
            onChange={(e) => props.onRadius(Number(e.target.value))}
          />
          <span className="hint">Flag pairs whose projects sit within this distance.</span>
        </label>
      </FilterMenu>
      <FilterMenu label={<>±{props.pad} days</>} active={props.pad !== DEFAULT_PAD}>
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
          <span className="hint">Widen each schedule before checking for overlap.</span>
        </label>
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
