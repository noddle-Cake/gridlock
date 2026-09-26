import type { Project } from '../types'
import { rangeLabel } from './format'

export interface TimelineItem {
  id: number
  group: string
  content: string
  start: string
  end: string
  title: string
  className: string
  style: string
}

/** Pure mapping from projects to timeline items (tested without a DOM). */
export function timelineItems(
  projects: Project[],
  pairedIds: Set<number>,
  selectedIds: Set<number>,
  colors: Record<string, string>,
): TimelineItem[] {
  return projects
    .filter((p) => p.start_date || p.end_date)
    .map((p) => {
      const start = (p.start_date ?? p.end_date)!
      const end = (p.end_date ?? p.start_date)!
      // vis-timeline ranges are end-exclusive; our end dates are inclusive days.
      const endExclusive = new Date(`${end}T00:00:00Z`)
      endExclusive.setUTCDate(endExclusive.getUTCDate() + 1)
      const classes = ['tl-item']
      if (pairedIds.has(p.id)) classes.push('tl-paired')
      if (selectedIds.has(p.id)) classes.push('tl-selected')
      if (p.approximate) classes.push('tl-approx')
      const when = rangeLabel(p.start_date, p.end_date, p.start_precision, p.end_precision)
      const color = colors[p.utility] ?? '#555'
      return {
        id: p.id,
        group: p.utility,
        content: p.name || 'Unnamed project',
        start,
        end: endExclusive.toISOString().slice(0, 10),
        title: `${p.name ?? 'Unnamed project'} — ${when}`,
        className: classes.join(' '),
        style: `border-color:${color};--tl-color:${color}`,
      }
    })
}
