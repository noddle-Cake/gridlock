import { useState } from 'react'

import { milesToKm, opportunityType } from '../lib/distanceBands'
import {
  OTHER_COLOR,
  bothBuildingLabel,
  durationLabel,
  num,
  overlapPct,
  plural,
  rulesLabel,
  usdRange,
} from '../lib/format'
import { SORT_LABELS, type SortKey } from '../lib/pairs'
import type { CoordinationPair, MatchRules, PairProject } from '../types'

interface Props {
  pairs: CoordinationPair[]
  /** The timing rules every pair met, stated above the list. */
  rules?: MatchRules | null
  /** Pairs before the map-view limit, to say how many are hidden off-screen. */
  totalCount?: number
  selectedId: string | null
  hoveredId?: string | null
  loading: boolean
  colorOf?: (p: PairProject) => string
  sort?: SortKey
  onSort?: (key: SortKey) => void
  limitToView?: boolean
  onLimitToView?: (on: boolean) => void
  onSelect: (pair: CoordinationPair) => void
  onHover?: (pair: CoordinationPair | null) => void
}

/**
 * Cards rendered per page. Thousands of pairs used to mount at once (~70k DOM nodes), so every
 * hover or colour change re-rendered the whole list.
 */
export const PAGE_SIZE = 50

function ProjectLine({ p, color }: { p: PairProject; color: string }) {
  const kind = [p.type, p.voltage_kv ? `${p.voltage_kv} kV` : null].filter(Boolean).join(' · ')
  return (
    <span className="card-project">
      <span className="swatch" style={{ background: color }} />
      <span className="card-project-text">
        <span className="card-project-name">{p.name || 'Unnamed'}</span>
        <span className="card-project-meta">
          {p.utility}
          {kind ? ` · ${kind}` : ''}
          {p.location_ref ? ` · ${p.location_ref}` : ''}
        </span>
      </span>
    </span>
  )
}

export function PairList({
  pairs,
  rules = null,
  totalCount = pairs.length,
  selectedId,
  hoveredId = null,
  loading,
  colorOf = () => OTHER_COLOR,
  sort = 'score',
  onSort,
  limitToView = false,
  onLimitToView,
  onSelect,
  onHover,
}: Props) {
  const offscreen = totalCount - pairs.length
  const [limit, setLimit] = useState(PAGE_SIZE)
  // A new sort starts again from the top page.
  const [sortedBy, setSortedBy] = useState(sort)
  if (sortedBy !== sort) {
    setSortedBy(sort)
    setLimit(PAGE_SIZE)
  }
  const more = pairs.length - limit
  return (
    <section className="pair-list" aria-label="Potential coordination opportunities">
      <header className="list-head">
        <div className="list-title">
          <h2>Potential coordination opportunities</h2>
          <span className="count" aria-live="polite">
            {loading
              ? 'updating…'
              : `${plural(pairs.length, 'result')}${
                  offscreen > 0 ? ` · ${num(offscreen)} outside map view` : ''
                }`}
          </span>
        </div>
        <div className="list-tools">
          {onLimitToView ? (
            <label className="toggle">
              <input
                type="checkbox"
                checked={limitToView}
                onChange={(e) => onLimitToView(e.target.checked)}
              />
              Only pairs in map view
            </label>
          ) : null}
          {onSort ? (
            <label className="sort">
              Sort
              <select value={sort} onChange={(e) => onSort(e.target.value as SortKey)}>
                {(Object.keys(SORT_LABELS) as SortKey[]).map((k) => (
                  <option key={k} value={k}>
                    {SORT_LABELS[k]}
                  </option>
                ))}
              </select>
            </label>
          ) : null}
        </div>
      </header>
      {rules ? (
        <p className="rules" data-testid="match-rules">
          {rulesLabel(rules.planning_from, rules.min_overlap_days)}
        </p>
      ) : null}
      <p className="disclaimer">
        Built on public filings. Planned projects are not commitments to build.
      </p>
      {pairs.length === 0 && !loading ? (
        <p className="empty">
          {offscreen > 0
            ? 'Nothing in this part of the map. Zoom out or turn off “Only pairs in map view”.'
            : 'No projects here are close in both place and time. Try more opportunity types or ' +
              'more utilities.'}
        </p>
      ) : null}
      <ol className="cards">
        {pairs.slice(0, limit).map((pair) => {
          const { project_a: a, project_b: b } = pair
          const type = opportunityType(pair.tier)
          const approximate = a.approximate || b.approximate
          const unverified = a.ownership_review_required || b.ownership_review_required
          return (
            <li key={pair.id}>
              <button
                type="button"
                className={`pair-card${pair.id === selectedId ? ' selected' : ''}${
                  pair.id === hoveredId ? ' hovered' : ''
                }`}
                aria-pressed={pair.id === selectedId}
                onClick={() => onSelect(pair)}
                onMouseEnter={() => onHover?.(pair)}
                onMouseLeave={() => onHover?.(null)}
                onFocus={() => onHover?.(pair)}
                onBlur={() => onHover?.(null)}
              >
                <span className="card-top">
                  {type ? (
                    <span className={`type-chip type-${type.tier}`} title={type.detail}>
                      {type.label}
                    </span>
                  ) : null}
                  <span className="card-stats">
                    <strong>{milesToKm(pair.miles).toFixed(1)} km</strong> apart ·{' '}
                    <strong className="together">{durationLabel(pair.overlap_days)}</strong>{' '}
                    building together
                  </span>
                  {pair.brief ? (
                    <span className={`badge ${pair.brief.stale ? 'badge-warn' : 'badge-ok'}`}>
                      {pair.brief.stale ? 'brief outdated' : 'brief ready'}
                    </span>
                  ) : null}
                </span>
                {pair.impact && pair.impact.if_aligned_high > 0 ? (
                  <span className="card-value" title="Rough, assumption-based estimate">
                    {pair.impact.total_high > 0
                      ? `≈ ${usdRange(pair.impact.total_low, pair.impact.total_high)} coordination value`
                      : `≈ ${usdRange(pair.impact.if_aligned_low, pair.impact.if_aligned_high)} if schedules aligned`}
                  </span>
                ) : null}
                <ProjectLine p={a} color={colorOf(a)} />
                <ProjectLine p={b} color={colorOf(b)} />
                <span className="card-foot">
                  <span className="both-building">
                    {bothBuildingLabel(pair)}
                    {pair.overlap_ratio != null
                      ? ` · ${overlapPct(pair.overlap_ratio)} of their build time`
                      : ''}
                  </span>
                  {approximate ? <span className="badge badge-approx">approx. location</span> : null}
                  {unverified ? (
                    <span className="badge badge-warn" title="Corporate ownership not verified: the two companies could share an owner.">
                      ownership unverified
                    </span>
                  ) : null}
                </span>
              </button>
            </li>
          )
        })}
      </ol>
      {more > 0 ? (
        <button type="button" className="show-more" onClick={() => setLimit((n) => n + PAGE_SIZE)}>
          Show {num(Math.min(more, PAGE_SIZE))} more of {num(more)}
        </button>
      ) : null}
    </section>
  )
}
