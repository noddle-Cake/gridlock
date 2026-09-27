import {
  type BandId,
  OPPORTUNITY_TYPES,
  selectedTypes,
  toggleType,
  typeSummary,
} from '../lib/distanceBands'
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
  const on = new Set(selectedTypes(props.bands).map((t) => t.tier))
  return (
    <>
      <FilterMenu
        label={
          <span className="chip-text">
            <span className="sr-only">Opportunity type: </span>
            {typeSummary(props.bands)}
          </span>
        }
        active={on.size !== OPPORTUNITY_TYPES.length}
      >
        <fieldset className="check-list type-list">
          <legend>Show opportunities to share</legend>
          {OPPORTUNITY_TYPES.map((t) => (
            <div key={t.tier} className="type-option">
              <label>
                <input
                  type="checkbox"
                  checked={on.has(t.tier)}
                  aria-describedby={`type-detail-${t.tier}`}
                  onChange={(e) => props.onBands(toggleType(props.bands, t, e.target.checked))}
                />
                <span className={`type-dot type-${t.tier}`} aria-hidden />
                {t.label}
              </label>
              <span className="type-detail" id={`type-detail-${t.tier}`}>
                {t.detail}
              </span>
            </div>
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
