import { FilterMenu } from './FilterMenu'

interface Props {
  utilities: string[]
  hidden: ReadonlySet<string>
  colors: Record<string, string>
  onChange: (hidden: Set<string>) => void
}

export function UtilityFilter({ utilities, hidden, colors, onChange }: Props) {
  const shown = utilities.filter((u) => !hidden.has(u)).length
  const label =
    hidden.size === 0 || utilities.length === 0
      ? 'All utilities'
      : `${shown} of ${utilities.length} utilities`

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
        {utilities.map((u) => (
          <label key={u}>
            <input
              type="checkbox"
              checked={!hidden.has(u)}
              onChange={(e) => toggle(u, e.target.checked)}
            />
            <span className="swatch" style={{ background: colors[u] ?? '#555' }} />
            {u}
          </label>
        ))}
        {hidden.size ? (
          <button type="button" className="link-button" onClick={() => onChange(new Set())}>
            Show all
          </button>
        ) : null}
      </fieldset>
    </FilterMenu>
  )
}
