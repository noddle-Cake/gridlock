import {
  type BandId,
  OPPORTUNITY_TYPES,
  selectedTypes,
  toggleType,
  typeSummary,
} from '../lib/distanceBands'
import { FilterMenu } from './FilterMenu'

interface Props {
  bands: BandId[]
  onBands: (v: BandId[]) => void
}

/**
 * The opportunity-type filter chip. The Review confidence cutoff used to sit beside it; it is
 * now fixed (DEFAULT_CONFIDENCE_THRESHOLD in lib/review.ts) so every planner sees the same
 * Review queue.
 */
export function ThresholdControls(props: Props) {
  const on = new Set(selectedTypes(props.bands).map((t) => t.tier))
  return (
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
  )
}
