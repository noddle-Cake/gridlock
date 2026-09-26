import { fireEvent, render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'

import { pair, project } from '../test/fixtures'
import { PAGE_SIZE, PairList } from './PairList'
import { ReviewTable } from './ReviewTable'
import { SourceLink } from './SourceLink'
import { ThresholdControls } from './ThresholdControls'
import { WhyFlaggedPanel } from './WhyFlaggedPanel'

const colors = { 'Keystone Electric': '#2f6fdf', 'Chesapeake Power': '#d9480f' }
const colorOf = (p: { utility: string }) => colors[p.utility as keyof typeof colors] ?? '#555'

describe('PairList', () => {
  it('renders a page of cards at a time', async () => {
    const pairs = Array.from({ length: PAGE_SIZE + 7 }, (_, i) => pair({ id: `p${i}` }))
    const { container } = render(
      <PairList pairs={pairs} selectedId={null} loading={false} onSelect={vi.fn()} />,
    )
    expect(container.querySelectorAll('.cards > li')).toHaveLength(PAGE_SIZE)
    await userEvent.click(screen.getByRole('button', { name: 'Show 7 more of 7' }))
    expect(container.querySelectorAll('.cards > li')).toHaveLength(PAGE_SIZE + 7)
    expect(screen.queryByRole('button', { name: /more of/ })).toBeNull()
  })
})

describe('WhyFlaggedPanel (Req 11)', () => {
  it('shows both projects side by side with distance, overlap days, and every factor', () => {
    render(<WhyFlaggedPanel pair={pair()} colorOf={colorOf} onGenerateBrief={vi.fn()} />)
    expect(screen.getByText('Hanover breakers')).toBeInTheDocument()
    expect(screen.getByText('Westminster breakers')).toBeInTheDocument()
    expect(screen.getByTestId('km')).toHaveTextContent('25.1') // 15.62 mi
    expect(screen.getByTestId('overlap-days')).toHaveTextContent('213')
    expect(screen.getByTestId('overlap-pct')).toHaveTextContent('58%')
    const factors = screen.getByRole('table', { name: 'Score factors' })
    for (const label of ['Distance', 'Time overlap', 'Same project type', 'Voltage similarity', 'Composite']) {
      expect(within(factors).getByText(label)).toBeInTheDocument()
    }
    expect(within(factors).getByText('0.38')).toBeInTheDocument()
    expect(within(factors).getByText('n/a')).toBeInTheDocument() // indeterminate voltage
  })

  it('shows the rough coordination value, counting timing items only if aligned', () => {
    const impact = {
      items: [
        { label: 'Share crews & equipment (one mobilization)', low: 150_000, high: 400_000,
          basis: 'flat range', acres: null, needs_timing: true },
        { label: 'Share access roads and permitting', low: 50_000, high: 200_000,
          basis: 'one permit package', acres: null, needs_timing: false },
      ],
      total_low: 50_000, total_high: 200_000, if_aligned_low: 200_000, if_aligned_high: 600_000,
      windows_overlap: false, acres: null, assumptions: ['Ranges are planning assumptions.'],
    }
    render(<WhyFlaggedPanel pair={pair({ impact })} colorOf={colorOf} onGenerateBrief={vi.fn()} />)
    const section = screen.getByRole('region', { name: 'Rough coordination value' })
    expect(within(section).getByTestId('impact-total')).toHaveTextContent('$50k–$200k')
    expect(section).toHaveTextContent('up to $200k–$600k if aligned')
    expect(within(section).getByText('Ranges are planning assumptions.')).toBeInTheDocument()
  })

  it('shows 0% and the in-service gap when build windows never meet', () => {
    const apart = pair({
      overlap_days: 0, overlap_ratio: 0, time_gap_days: 400, window_start: null, window_end: null,
    })
    render(<WhyFlaggedPanel pair={apart} colorOf={colorOf} onGenerateBrief={vi.fn()} />)
    expect(screen.getByTestId('overlap-pct')).toHaveTextContent('0%')
    expect(screen.getByTestId('time-gap')).toHaveTextContent('13 months')
    expect(screen.getByTestId('overlap-days')).toHaveTextContent('None')
  })

  it('draws both build windows, hatching the stretch both are building', () => {
    const windows = {
      build_a: ['2026-01-01', '2026-06-30'] as [string, string],
      build_b: ['2026-04-01', '2026-12-31'] as [string, string],
      window_start: '2026-04-01',
      window_end: '2026-06-30',
    }
    const { container, rerender } = render(
      <WhyFlaggedPanel pair={pair(windows)} colorOf={colorOf} onGenerateBrief={vi.fn()} />,
    )
    const strip = screen.getByRole('region', { name: 'Build windows' })
    const bars = container.querySelectorAll<HTMLElement>('.bw-bar')
    expect(bars).toHaveLength(2)
    expect(bars[0].style.background).toBe('rgb(47, 111, 223)') // project A's utility colour
    expect(within(strip).getByTestId('bw-shared')).toHaveTextContent('Both building')

    // Windows that never meet: two bars, no hatching.
    const apart = { ...windows, build_b: ['2028-01-01', '2028-12-31'] as [string, string] }
    rerender(
      <WhyFlaggedPanel
        pair={pair({ ...apart, window_start: null, window_end: null })}
        colorOf={colorOf}
        onGenerateBrief={vi.fn()}
      />,
    )
    expect(container.querySelectorAll('.bw-bar')).toHaveLength(2)
    expect(screen.queryByTestId('bw-shared')).toBeNull()
  })

  it('says explicitly when no brief exists, and shows one when it does', () => {
    const { rerender } = render(
      <WhyFlaggedPanel pair={pair()} colorOf={colorOf} onGenerateBrief={vi.fn()} />,
    )
    expect(screen.getByTestId('no-brief')).toHaveTextContent('No coordination brief')
    const brief = { pair_id: '1-2', text: 'Share a crane crew.', generated_at: '', stale: false }
    rerender(<WhyFlaggedPanel pair={pair({ brief })} colorOf={colorOf} onGenerateBrief={vi.fn()} />)
    expect(screen.getByTestId('brief-text')).toHaveTextContent('Share a crane crew.')
    expect(screen.queryByTestId('no-brief')).toBeNull()
    expect(screen.queryByText('template')).toBeNull()
    rerender(
      <WhyFlaggedPanel
        pair={pair({ brief: { ...brief, source: 'template' } })}
        colorOf={colorOf}
        onGenerateBrief={vi.fn()}
      />,
    )
    expect(screen.getByText('template')).toBeInTheDocument()
  })

  it('requests a brief for the selected pair', async () => {
    const onGenerate = vi.fn().mockResolvedValue({})
    render(<WhyFlaggedPanel pair={pair()} colorOf={colorOf} onGenerateBrief={onGenerate} />)
    await userEvent.click(screen.getByRole('button', { name: 'Generate brief' }))
    expect(onGenerate).toHaveBeenCalledWith(expect.objectContaining({ id: '1-2' }))
  })
})

describe('ReviewTable (Req 3.3, 13.1-13.3)', () => {
  const projects = [
    project({ id: 1, confidence: 0.9 }),
    project({ id: 2, name: 'Unsure one', confidence: 0.7 }),
    project({ id: 3, name: 'Shaky', confidence: 0.4 }),
  ]

  it('visually distinguishes projects at or below the confidence threshold', async () => {
    render(<ReviewTable projects={projects} threshold={0.7} colors={colors} onPatch={vi.fn()} />)
    await userEvent.click(screen.getByLabelText('Only show projects needing review'))
    expect(screen.getByTestId('review-row-1')).not.toHaveClass('needs-review')
    expect(screen.getByTestId('review-row-2')).toHaveClass('needs-review')
    expect(screen.getByTestId('review-row-3')).toHaveClass('needs-review')
  })

  it('marks a project reviewed via PATCH', async () => {
    const onPatch = vi.fn().mockResolvedValue(project())
    render(<ReviewTable projects={projects} threshold={0.7} colors={colors} onPatch={onPatch} />)
    await userEvent.click(screen.getByLabelText('Mark Shaky reviewed'))
    expect(onPatch).toHaveBeenCalledWith(3, { reviewed: true })
  })

  it('submits inline edits with only the changed fields', async () => {
    const onPatch = vi.fn().mockResolvedValue(project())
    render(<ReviewTable projects={projects} threshold={0.7} colors={colors} onPatch={onPatch} />)
    const row = screen.getByTestId('review-row-3')
    await userEvent.click(within(row).getByRole('button', { name: 'Edit' }))
    const name = screen.getByLabelText('name for Shaky')
    await userEvent.clear(name)
    await userEvent.type(name, 'Firm')
    await userEvent.click(screen.getByRole('button', { name: 'Save' }))
    expect(onPatch).toHaveBeenCalledWith(3, { name: 'Firm' })
  })
})

describe('ThresholdControls (Req 10.1, 10.2)', () => {
  it('reports confidence changes and has no date-padding control', () => {
    const onConfidence = vi.fn()
    render(
      <ThresholdControls
        bands={['touching', '1.6', '8', '25', '40']}
        confidenceThreshold={0.7}
        onBands={vi.fn()}
        onConfidenceThreshold={onConfidence}
      />,
    )
    fireEvent.change(screen.getByLabelText('Confidence threshold'), { target: { value: '0.5' } })
    expect(onConfidence).toHaveBeenCalledWith(0.5)
    expect(screen.queryByText(/Build window/)).toBeNull()
  })

  it('toggles non-overlapping distance bands from the dropdown', async () => {
    const onBands = vi.fn()
    render(
      <ThresholdControls
        bands={['touching', '8', '40']}
        confidenceThreshold={0.7}
        onBands={onBands}
        onConfidenceThreshold={vi.fn()}
      />,
    )
    expect(screen.getByText(/Distance apart:/).parentElement).toHaveTextContent(
      'Touching / crossing, 1.6–8 km, 25–40 km',
    )
    await userEvent.click(screen.getByText(/Distance apart:/))
    const options = screen.getAllByRole('checkbox').map((c) => c.parentElement?.textContent)
    expect(options).toEqual([
      'Touching / crossing',
      'Under 1.6 km',
      '1.6–8 km',
      '8–25 km',
      '25–40 km',
    ])

    await userEvent.click(screen.getByRole('checkbox', { name: '8–25 km' }))
    expect(onBands).toHaveBeenLastCalledWith(['touching', '8', '25', '40'])
    await userEvent.click(screen.getByRole('checkbox', { name: 'Touching / crossing' }))
    expect(onBands).toHaveBeenLastCalledWith(['8', '40'])
  })
})

describe('SourceLink (Req 12)', () => {
  it('opens the source page in a new tab', () => {
    render(<SourceLink url="https://x.test/plan.pdf" page={7} />)
    const link = screen.getByRole('link')
    expect(link).toHaveAttribute('href', 'https://x.test/plan.pdf#page=7')
    expect(link).toHaveAttribute('target', '_blank')
    expect(link).toHaveAttribute('rel', expect.stringContaining('noopener'))
  })
})
