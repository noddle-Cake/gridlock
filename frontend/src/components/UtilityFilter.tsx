import { useMemo, useState } from 'react'

import { CHALLENGE_LABEL, CHALLENGE_UTILITIES, focusHidden } from '../lib/focus'
import { OTHER_COLOR } from '../lib/format'
import { FilterMenu } from './FilterMenu'

/** Rows rendered at once; with ~1,000 developers the search narrows the rest. */
const MAX_ROWS = 100

interface Props {
  utilities: string[]
  /** Projects per utility, to list the busiest first. */
  counts?: ReadonlyMap<string, number>
  hidden: ReadonlySet<string>
  colors: Record<string, string>
  onChange: (hidden: Set<string>) => void
}

export function UtilityFilter({ utilities, counts, hidden, colors, onChange }: Props) {
  const [query, setQuery] = useState('')
  const shown = utilities.filter((u) => !hidden.has(u)).length
  const challenge = focusHidden(utilities)
  const onlyChallenge =
    challenge != null && shown === 2 && CHALLENGE_UTILITIES.every((u) => !hidden.has(u))
  const label =
    hidden.size === 0 || utilities.length === 0
      ? 'All utilities'
      : onlyChallenge
        ? CHALLENGE_LABEL
        : `${shown} of ${utilities.length} utilities`

  const sorted = useMemo(
    () =>
      counts
        ? [...utilities].sort((a, b) => (counts.get(b) ?? 0) - (counts.get(a) ?? 0) || a.localeCompare(b))
        : utilities,
    [utilities, counts],
  )
  const q = query.trim().toLowerCase()
  const matches = q ? sorted.filter((u) => u.toLowerCase().includes(q)) : sorted

  function toggle(u: string, on: boolean) {
    const next = new Set(hidden)
    if (on) next.delete(u)
    else next.add(u)
    onChange(next)
  }

  return (
    <FilterMenu label={label} active={hidden.size > 0}>
      <fieldset className="check-list">
        <legend>Show projects from</legend>
        {utilities.length === 0 ? <p className="empty">No utilities loaded yet.</p> : null}
        {utilities.length > 12 ? (
          <input
            type="search"
            className="check-list-search"
            placeholder={`Search ${utilities.length} companies`}
            aria-label="Search companies"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
          />
        ) : null}
        <div className="check-list-actions">
          {challenge && !onlyChallenge ? (
            <button type="button" className="link-button" onClick={() => onChange(challenge)}>
              Only {CHALLENGE_LABEL}
            </button>
          ) : null}
          {hidden.size ? (
            <button type="button" className="link-button" onClick={() => onChange(new Set())}>
              Show all
            </button>
          ) : null}
          {q && matches.length ? (
            <button
              type="button"
              className="link-button"
              onClick={() => {
                const keep = new Set(matches)
                onChange(new Set(utilities.filter((u) => !keep.has(u))))
              }}
            >
              Only {matches.length === 1 ? 'this one' : `these ${matches.length}`}
            </button>
          ) : null}
        </div>
        <div className="check-list-rows">
          {matches.slice(0, MAX_ROWS).map((u) => (
            <label key={u}>
              <input
                type="checkbox"
                checked={!hidden.has(u)}
                onChange={(e) => toggle(u, e.target.checked)}
              />
              <span className="swatch" style={{ background: colors[u] ?? OTHER_COLOR }} />
              <span className="check-list-name">{u}</span>
              {counts ? <span className="check-list-count">{counts.get(u) ?? 0}</span> : null}
            </label>
          ))}
        </div>
        {matches.length > MAX_ROWS ? (
          <p className="empty">
            {matches.length - MAX_ROWS} more — search to narrow the list.
          </p>
        ) : null}
        {q && !matches.length ? <p className="empty">No company matches “{query}”.</p> : null}
      </fieldset>
    </FilterMenu>
  )
}
