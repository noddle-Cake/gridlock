import type { AiJob } from '../lib/useAiJobs'

const STATUS: Record<AiJob['kind'], Record<AiJob['status'], string>> = {
  brief: { running: 'Drafting brief', done: 'Brief ready', error: 'Brief failed' },
  ask: { running: 'Answering', done: 'Answer ready', error: 'Answer failed' },
}

interface Props {
  jobs: AiJob[]
  onOpen: (job: AiJob) => void
  onDismiss: (job: AiJob) => void
}

/**
 * Header strip for AI work running in the background: what is still running, and what
 * finished while the planner was looking elsewhere. Clicking one goes to its result.
 */
export function JobTray({ jobs, onOpen, onDismiss }: Props) {
  const shown = jobs.filter((j) => j.status === 'running' || j.unseen)
  return (
    <div className="job-tray" role="status" aria-label="AI activity">
      {shown.map((j) => (
        <div key={j.id} className={`job job-${j.status}`}>
          <button
            type="button"
            className="job-open"
            title={j.status === 'error' ? j.error : `Open: ${j.title}`}
            onClick={() => onOpen(j)}
          >
            {j.status === 'running' ? <span className="job-spinner" aria-hidden /> : null}
            <span className="job-status">{STATUS[j.kind][j.status]}</span>
            <span className="job-title">{j.title}</span>
          </button>
          {j.status !== 'running' ? (
            <button
              type="button"
              className="job-dismiss"
              aria-label={`Dismiss: ${STATUS[j.kind][j.status]}`}
              onClick={() => onDismiss(j)}
            >
              ×
            </button>
          ) : null}
        </div>
      ))}
    </div>
  )
}
