import { useCallback, useEffect, useRef, useState } from 'react'

import type { AskResponse } from '../types'

// AI work (a coordination brief, an Ask GridMerge answer) takes seconds to a minute. It runs
// here, outside the panel that started it, so closing that panel, opening another pair or
// switching tabs doesn't lose it. A job that finishes while its result is off screen stays
// in the header tray until the planner opens or dismisses it.

export type AiJobKind = 'brief' | 'ask'

export interface AiJob {
  id: number
  kind: AiJobKind
  /** What it is about: "Hanover breakers ↔ Westminster breakers", or the question. */
  title: string
  status: 'running' | 'done' | 'error'
  error?: string
  /** Brief jobs: the pair it drafts for. */
  pairId?: string
  /** Ask jobs: the question and, once done, the answer. */
  question?: string
  answer?: AskResponse
  /** Finished while its result was off screen: shown in the tray until opened/dismissed. */
  unseen: boolean
}

export interface StartOptions<T> {
  /** Called with the result before the job is marked done (e.g. store the brief). */
  onDone?: (result: T) => void
  /** Whether the planner is looking at this job's result right now. */
  onScreen: () => boolean
  describe: (e: unknown) => string
}

export function useAiJobs() {
  const [jobs, setJobs] = useState<AiJob[]>([])
  const nextId = useRef(1)

  const update = useCallback((id: number, patch: Partial<AiJob>) => {
    setJobs((js) => js.map((j) => (j.id === id ? { ...j, ...patch } : j)))
  }, [])

  const start = useCallback(
    <T>(
      job: Pick<AiJob, 'kind' | 'title' | 'pairId' | 'question'>,
      run: () => Promise<T>,
      { onDone, onScreen, describe }: StartOptions<T>,
    ): number => {
      const id = nextId.current++
      // A new brief for a pair replaces that pair's finished ones (and their errors).
      setJobs((js) => [
        ...js.filter((j) => !(job.pairId && j.pairId === job.pairId && j.status !== 'running')),
        { ...job, id, status: 'running', unseen: false },
      ])
      run().then(
        (result) => {
          onDone?.(result)
          const answer = job.kind === 'ask' ? (result as AskResponse) : undefined
          update(id, { status: 'done', answer, unseen: !onScreen() })
        },
        (e) => update(id, { status: 'error', error: describe(e), unseen: !onScreen() }),
      )
      return id
    },
    [update],
  )

  /** Opened or dismissed: out of the tray (an answer stays until its panel is closed). */
  const markSeen = useCallback((id: number) => update(id, { unseen: false }), [update])

  /** Forget a finished job; a running one keeps going. */
  const remove = useCallback((id: number) => {
    setJobs((js) => js.filter((j) => j.id !== id || j.status === 'running'))
  }, [])

  // Finished work is announced in the browser tab too, for when the planner is elsewhere.
  const unseen = jobs.filter((j) => j.unseen).length
  useEffect(() => {
    const base = document.title.replace(/^\(\d+\) /, '')
    document.title = unseen ? `(${unseen}) ${base}` : base
  }, [unseen])

  return { jobs, start, markSeen, remove }
}
