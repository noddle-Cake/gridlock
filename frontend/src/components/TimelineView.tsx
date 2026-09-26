import 'vis-timeline/styles/vis-timeline-graph2d.css'

import { useEffect, useRef } from 'react'
import * as vis from 'vis-timeline/standalone'
import { Timeline } from 'vis-timeline/standalone'

import { type TimelineItem, timelineItems } from '../lib/timelineItems'
import type { CoordinationPair, Project } from '../types'

// The standalone bundle ships DataSet at runtime but omits it from its type declarations.
interface DataSetLike<T> {
  add(items: T[]): void
  clear(): void
}
const DataSet = (vis as unknown as { DataSet: new <T>() => DataSetLike<T> }).DataSet

interface Props {
  projects: Project[]
  pairs: CoordinationPair[]
  selectedPair: CoordinationPair | null
  colors: Record<string, string>
  onSelectProject: (p: Project) => void
}

export function TimelineView({ projects, pairs, selectedPair, colors, onSelectProject }: Props) {
  const container = useRef<HTMLDivElement>(null)
  const timeline = useRef<Timeline | null>(null)
  const items = useRef(new DataSet<TimelineItem>())
  const groups = useRef(new DataSet<{ id: string; content: string }>())
  const selectRef = useRef(onSelectProject)
  useEffect(() => {
    selectRef.current = onSelectProject
  }, [onSelectProject])
  const byId = useRef(new Map<number, Project>())

  useEffect(() => {
    if (!container.current) return
    const tl = new Timeline(container.current, items.current as never, groups.current as never, {
      stack: true,
      zoomable: true,
      horizontalScroll: true,
      zoomKey: 'ctrlKey',
      orientation: 'top',
      margin: { item: 4 },
      tooltip: { followMouse: true },
    })
    tl.on('select', (props: { items: number[] }) => {
      const p = byId.current.get(props.items[0])
      if (p) selectRef.current(p)
    })
    timeline.current = tl
    return () => {
      tl.destroy()
      timeline.current = null
    }
  }, [])

  useEffect(() => {
    byId.current = new Map(projects.map((p) => [p.id, p]))
    const pairedIds = new Set(pairs.flatMap((p) => [p.project_a.id, p.project_b.id]))
    const selectedIds = new Set(
      selectedPair ? [selectedPair.project_a.id, selectedPair.project_b.id] : [],
    )
    const next = timelineItems(projects, pairedIds, selectedIds, colors)
    groups.current.clear()
    groups.current.add(
      Object.keys(colors).map((u) => ({
        id: u,
        content: `<span class="tl-group" style="--tl-color:${colors[u]}">${escapeHtml(u)}</span>`,
      })),
    )
    items.current.clear()
    items.current.add(next.map((i) => ({ ...i, content: escapeHtml(i.content) })))
  }, [projects, pairs, selectedPair, colors])

  // Separate from the data effect so refreshes don't restart the zoom animation.
  const windowStart = selectedPair?.window_start
  const windowEnd = selectedPair?.window_end
  useEffect(() => {
    if (!windowStart || !windowEnd || !timeline.current) return
    timeline.current.setWindow(new Date(windowStart), new Date(windowEnd), {
      animation: { duration: 600, easingFunction: 'easeInOutCubic' },
    })
  }, [selectedPair?.id, windowStart, windowEnd])

  return <div ref={container} className="timeline" aria-label="Project timeline" />
}

function escapeHtml(s: string): string {
  return s.replace(/[&<>"']/g, (c) => `&#${c.charCodeAt(0)};`)
}
