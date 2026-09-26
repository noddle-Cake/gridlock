import type { ReactNode } from 'react'

import type { AskResponse, AskToolCall, Project } from '../types'

export type AskState =
  | { status: 'loading'; question: string }
  | { status: 'done'; question: string; response: AskResponse }
  | { status: 'error'; question: string; message: string }

interface Props {
  state: AskState
  onSelectProject: (p: Project) => void
  onClose: () => void
  onRetry: () => void
}

const TOOL_LABELS: Record<string, string> = {
  search_gridmerge: 'Searched projects',
  get_project_details: 'Opened project',
  find_coordination_overlaps: 'Checked coordination pairs',
}

// **bold**, and project citations like [#12] or [#12, #15].
const INLINE = /(\*\*[^*]+\*\*|\[#\d+(?:\s*,\s*#?\d+)*\])/g

function Inline({
  text,
  byId,
  onSelect,
}: {
  text: string
  byId: Map<number, Project>
  onSelect: (p: Project) => void
}) {
  const out: ReactNode[] = []
  text.split(INLINE).forEach((part, i) => {
    if (!part) return
    if (part.startsWith('**') && part.endsWith('**')) {
      out.push(<strong key={i}>{part.slice(2, -2)}</strong>)
      return
    }
    if (part.startsWith('[#')) {
      for (const m of part.matchAll(/\d+/g)) {
        const p = byId.get(Number(m[0]))
        out.push(
          p ? (
            <button
              key={`${i}-${m[0]}`}
              type="button"
              className="cite"
              title={[p.name, p.utility].filter(Boolean).join(' · ')}
              onClick={() => onSelect(p)}
            >
              #{p.id}
            </button>
          ) : (
            <span key={`${i}-${m[0]}`} className="cite missing">
              #{m[0]}
            </span>
          ),
        )
      }
      return
    }
    out.push(part)
  })
  return <>{out}</>
}

/** The model's plain-text answer: paragraphs, "- " bullets, **bold**, and citations. */
export function AnswerText({
  text,
  projects,
  onSelect,
}: {
  text: string
  projects: Project[]
  onSelect: (p: Project) => void
}) {
  const byId = new Map(projects.map((p) => [p.id, p]))
  const blocks: ReactNode[] = []
  let bullets: string[] = []
  const flush = () => {
    if (!bullets.length) return
    const items = bullets
    blocks.push(
      <ul key={`ul${blocks.length}`}>
        {items.map((b, i) => (
          <li key={i}>
            <Inline text={b} byId={byId} onSelect={onSelect} />
          </li>
        ))}
      </ul>,
    )
    bullets = []
  }
  for (const raw of text.split('\n')) {
    const line = raw.trim()
    const bullet = /^[-*•]\s+(.*)$/.exec(line)
    if (bullet) {
      bullets.push(bullet[1])
      continue
    }
    flush()
    if (line) {
      blocks.push(
        <p key={`p${blocks.length}`}>
          <Inline text={line.replace(/^#+\s*/, '')} byId={byId} onSelect={onSelect} />
        </p>,
      )
    }
  }
  flush()
  return <div className="ask-answer">{blocks}</div>
}

function describeCall(c: AskToolCall): string {
  const args = Object.entries(c.arguments)
    .filter(([, v]) => v !== '' && v != null)
    .map(([k, v]) => `${k.replace(/_/g, ' ')}: ${String(v)}`)
    .join(', ')
  return `${TOOL_LABELS[c.name] ?? c.name}${args ? ` (${args})` : ''} → ${c.summary}`
}

/** "Ask GridMerge": the AI answer, grounded in GridMerge data, above the pair list. */
export function AskPanel({ state, onSelectProject, onClose, onRetry }: Props) {
  return (
    <section className="ask-panel" aria-label="Ask GridMerge" aria-busy={state.status === 'loading'}>
      <header className="ask-head">
        <span className="ask-title">
          <span aria-hidden="true">✨</span> Ask GridMerge
        </span>
        <button type="button" className="ask-close" aria-label="Close answer" onClick={onClose}>
          ×
        </button>
      </header>
      <p className="ask-question">{state.question}</p>

      {state.status === 'loading' ? (
        <p className="ask-status" role="status">
          <span className="ss-spinner" aria-hidden="true" /> Searching GridMerge data…
        </p>
      ) : null}

      {state.status === 'error' ? (
        <div className="ask-status error" role="alert">
          <p>{state.message}</p>
          <button type="button" className="linkish" onClick={onRetry}>
            Try again
          </button>
        </div>
      ) : null}

      {state.status === 'done' ? (
        <>
          <AnswerText
            text={state.response.answer}
            projects={state.response.projects}
            onSelect={onSelectProject}
          />
          {state.response.projects.length ? (
            <div className="ask-projects">
              <h3>Projects</h3>
              <ul>
                {state.response.projects.map((p) => (
                  <li key={p.id}>
                    <button type="button" onClick={() => onSelectProject(p)}>
                      <span className="ask-project-name">{p.name ?? `Project ${p.id}`}</span>
                      <span className="ask-project-meta">
                        #{p.id} · {[p.utility, p.type, p.state].filter(Boolean).join(' · ')}
                      </span>
                    </button>
                  </li>
                ))}
              </ul>
            </div>
          ) : null}
          {state.response.tool_calls.length ? (
            <details className="ask-trace">
              <summary>How this was answered</summary>
              <ul>
                {state.response.tool_calls.map((c, i) => (
                  <li key={i}>{describeCall(c)}</li>
                ))}
              </ul>
            </details>
          ) : null}
          <p className="ask-note">
            Answered by Gemini from GridMerge records only. Check key facts against the source
            plans.
          </p>
        </>
      ) : null}
    </section>
  )
}
