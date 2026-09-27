import {
  type KeyboardEvent,
  type ReactNode,
  useEffect,
  useId,
  useMemo,
  useRef,
  useState,
} from 'react'

import { num, plural } from '../lib/format'
import type {
  CompanySuggestion,
  LocationSuggestion,
  SearchHit,
  SearchInterpretation,
  SearchResponse,
} from '../types'

const MAX_PROJECTS = 5

interface Props {
  value: string
  onChange: (q: string) => void
  /** The /search answer for `value`, or null while it loads or when the API is down. */
  result: SearchResponse | null
  loading: boolean
  error?: string | null
  /** Enter on plain text: keep the text as the filter and frame its matches. */
  onApply: () => void
  onPickCompany: (c: CompanySuggestion) => void
  onPickLocation: (l: LocationSuggestion) => void
  onPickProject: (p: SearchHit) => void
  onAsk: (question: string) => void
  /** Guests can see Ask GridMerge but must sign in to use it (onAsk then signs in). */
  aiLocked?: boolean
}

type Option =
  | { kind: 'ask'; key: string }
  | { kind: 'company'; key: string; company: CompanySuggestion }
  | { kind: 'location'; key: string; location: LocationSuggestion }
  | { kind: 'project'; key: string; project: SearchHit }
  | { kind: 'all'; key: string }

function buildOptions(value: string, result: SearchResponse | null): Option[] {
  const q = value.trim()
  if (!q) return []
  const ask: Option = { kind: 'ask', key: 'ask' }
  const out: Option[] = []
  // A question offers the AI first; a lookup offers it last.
  if (result?.suggest_ai) out.push(ask)
  for (const c of result?.companies ?? []) out.push({ kind: 'company', key: `c:${c.utility}`, company: c })
  for (const l of result?.locations ?? []) out.push({ kind: 'location', key: `l:${l.code}`, location: l })
  for (const p of (result?.projects ?? []).slice(0, MAX_PROJECTS))
    out.push({ kind: 'project', key: `p:${p.id}`, project: p })
  if (result && result.total > 0) out.push({ kind: 'all', key: 'all' })
  if (!result?.suggest_ai) out.push(ask)
  return out
}

/** "FPL · ZIP 33101 (100 mi) · transmission line" — how the query was read. */
function describeInterpretation(i: SearchInterpretation): string[] {
  const parts: string[] = [...i.utilities]
  if (i.zip) {
    if (!i.zip_found) parts.push(`ZIP ${i.zip} not found`)
    else parts.push(i.radius_miles ? `ZIP ${i.zip} (${i.radius_miles} mi)` : `ZIP ${i.zip}`)
  }
  parts.push(...i.states, ...i.types)
  if (i.terms.length) parts.push(`“${i.terms.join(' ')}”`)
  return parts
}

function Group({ label, children }: { label: string; children: ReactNode }) {
  return (
    <li role="presentation" className="ss-group">
      <div className="ss-group-label" aria-hidden="true">
        {label}
      </div>
      <ul role="group" aria-label={label}>
        {children}
      </ul>
    </li>
  )
}

function Count({ n }: { n: number }) {
  return (
    <span className="ss-count">
      {plural(n, 'project')}
    </span>
  )
}

/**
 * The search bar: company, state, ZIP code, or project text, with grouped suggestions
 * from GET /search, and an "Ask GridMerge" option that sends the text to the AI.
 */
export function SmartSearch({
  value,
  onChange,
  result,
  loading,
  error = null,
  onApply,
  onPickCompany,
  onPickLocation,
  onPickProject,
  onAsk,
  aiLocked = false,
}: Props) {
  const [open, setOpen] = useState(false)
  // Tracked by key, so the highlight survives a fresh answer that still offers it.
  const [activeKey, setActiveKey] = useState<string | null>(null)
  const wrap = useRef<HTMLDivElement>(null)
  const listId = useId()
  const options = useMemo(() => buildOptions(value, result), [value, result])
  const active = options.findIndex((o) => o.key === activeKey)
  const setActive = (i: number) => setActiveKey(options[i]?.key ?? null)
  const q = value.trim()

  useEffect(() => {
    if (!open) return
    function onPointer(e: PointerEvent) {
      if (!wrap.current?.contains(e.target as Node)) setOpen(false)
    }
    document.addEventListener('pointerdown', onPointer)
    return () => document.removeEventListener('pointerdown', onPointer)
  }, [open])

  function choose(o: Option) {
    setOpen(false)
    switch (o.kind) {
      case 'ask':
        return onAsk(q)
      case 'company':
        return onPickCompany(o.company)
      case 'location':
        return onPickLocation(o.location)
      case 'project':
        return onPickProject(o.project)
      default:
        return onApply()
    }
  }

  function onKeyDown(e: KeyboardEvent<HTMLInputElement>) {
    if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
      const n = options.length
      if (!n) return
      e.preventDefault()
      setOpen(true)
      // Cycles through the options and back to the text itself (-1).
      if (e.key === 'ArrowDown') setActive(active >= n - 1 ? -1 : active + 1)
      else setActive(active <= -1 ? n - 1 : active - 1)
      return
    }
    if (e.key === 'Escape') {
      if (open) {
        e.preventDefault()
        setOpen(false)
      }
      return
    }
    if (e.key === 'Enter') {
      e.preventDefault()
      const o = open ? options[active] : undefined
      if (o) choose(o)
      else if (!q) return
      else if (result?.suggest_ai) choose({ kind: 'ask', key: 'ask' })
      else choose({ kind: 'all', key: 'all' })
    }
  }

  const optionId = (i: number) => `${listId}-o${i}`
  const activeOption = options[active]
  const showList = open && q.length > 0

  function renderOption(o: Option, content: ReactNode) {
    const i = options.indexOf(o)
    return (
      <li
        key={o.key}
        id={optionId(i)}
        role="option"
        aria-selected={i === active}
        className={`ss-option ss-${o.kind}${i === active ? ' active' : ''}`}
        onPointerDown={(e) => e.preventDefault() /* keep focus in the input */}
        onPointerEnter={() => setActive(i)}
        onClick={() => choose(o)}
      >
        {content}
      </li>
    )
  }

  const askOption = options.find((o) => o.kind === 'ask')
  const askRow = askOption
    ? renderOption(
        askOption,
        <>
          <span className="ss-spark" aria-hidden="true">
            ✨
          </span>
          <span className="ss-main">
            Ask GridMerge <span className="ss-quote">“{q}”</span>
          </span>
          {aiLocked ? <span className="ss-lock">Sign in</span> : null}
        </>,
      )
    : null
  const companies = options.filter((o) => o.kind === 'company')
  const locations = options.filter((o) => o.kind === 'location')
  const projects = options.filter((o) => o.kind === 'project')
  const all = options.find((o) => o.kind === 'all')
  const reading = result ? describeInterpretation(result.interpretation) : []

  return (
    <div className="smart-search" ref={wrap}>
      <div className="search">
        <svg width="16" height="16" viewBox="0 0 16 16" aria-hidden="true">
          <circle cx="7" cy="7" r="4.5" fill="none" stroke="currentColor" strokeWidth="1.6" />
          <path d="m10.5 10.5 3 3" stroke="currentColor" strokeWidth="1.6" />
        </svg>
        <input
          type="search"
          role="combobox"
          placeholder="Search company, state, ZIP, or ask a question"
          aria-label="Search GridMerge"
          aria-autocomplete="list"
          aria-expanded={showList}
          aria-controls={listId}
          aria-activedescendant={showList && activeOption ? optionId(active) : undefined}
          value={value}
          onChange={(e) => {
            onChange(e.target.value)
            setOpen(true)
          }}
          onFocus={() => setOpen(true)}
          onKeyDown={onKeyDown}
        />
        {loading ? <span className="ss-spinner" aria-hidden="true" /> : null}
        <button
          type="button"
          className="ss-ask-button"
          aria-label="Ask GridMerge"
          title={
            aiLocked
              ? 'Sign in to ask GridMerge (AI answer from GridMerge data)'
              : 'Ask GridMerge (AI answer from GridMerge data)'
          }
          disabled={!q}
          onClick={() => {
            setOpen(false)
            onAsk(q)
          }}
        >
          ✨ <span>AI</span>
        </button>
      </div>

      {!showList && error ? <p className="ss-empty" role="alert">{error}</p> : null}
      {showList ? (
        <div className="ss-popover">
          {error ? <p className="ss-empty" role="alert">{error}</p> : null}
          {reading.length ? (
            <p className="ss-reading">
              {result!.interpretation.fuzzy ? 'Close matches for ' : 'Searching '}
              {reading.map((r) => (
                <span key={r} className="ss-token">
                  {r}
                </span>
              ))}
            </p>
          ) : null}
          <ul id={listId} role="listbox" aria-label="Search suggestions" className="ss-list">
            {result?.suggest_ai ? askRow : null}
            {companies.length ? (
              <Group label="Companies">
                {companies.map((o) =>
                  renderOption(
                    o,
                    <>
                      <span className="ss-main">{o.kind === 'company' && o.company.utility}</span>
                      {o.kind === 'company' ? <Count n={o.company.project_count} /> : null}
                    </>,
                  ),
                )}
              </Group>
            ) : null}
            {locations.length ? (
              <Group label="Locations">
                {locations.map((o) =>
                  renderOption(
                    o,
                    <>
                      <span className="ss-main">{o.kind === 'location' && o.location.label}</span>
                      {o.kind === 'location' ? <Count n={o.location.project_count} /> : null}
                    </>,
                  ),
                )}
              </Group>
            ) : null}
            {projects.length ? (
              <Group label="Projects">
                {projects.map((o) => {
                  if (o.kind !== 'project') return null
                  const p = o.project
                  return renderOption(
                    o,
                    <>
                      <span className="ss-main">
                        {p.name ?? `Project ${p.id}`}
                        <span className="ss-sub">
                          {[p.utility, p.type, p.state].filter(Boolean).join(' · ')}
                        </span>
                      </span>
                      {p.miles != null ? <span className="ss-count">{p.miles} mi</span> : null}
                    </>,
                  )
                })}
              </Group>
            ) : null}
            {all
              ? renderOption(
                  all,
                  <span className="ss-main">
                    Show all {num(result!.total)} matching{' '}
                    {result!.total === 1 ? 'project' : 'projects'} on the map
                  </span>,
                )
              : null}
            {result && !result.total ? (
              <li role="presentation" className="ss-empty">
                {result.interpretation.zip_found
                  ? `No matching planned projects within ${result.interpretation.radius_miles} mi of ZIP ${result.interpretation.zip}.`
                  : `No projects match “${q}”.`}
              </li>
            ) : null}
            {!result && loading ? (
              <li role="presentation" className="ss-empty">
                Searching…
              </li>
            ) : null}
            {result?.suggest_ai ? null : askRow}
          </ul>
        </div>
      ) : null}
    </div>
  )
}
