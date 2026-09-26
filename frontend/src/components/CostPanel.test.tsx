import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'

import { money } from '../lib/format'
import { allocation, estimate, pair } from '../test/fixtures'
import { CostPanel } from './CostPanel'

describe('CostPanel', () => {
  it('shows stand-alone estimates, joint savings and every split against the stand-alone test', async () => {
    render(<CostPanel pair={pair()} onAllocate={vi.fn().mockResolvedValue(allocation())} />)
    const estimates = await screen.findByRole('table', { name: 'Stand-alone estimates' })
    expect(within(estimates).getByText('$2.2M')).toBeInTheDocument()
    expect(within(estimates).getByText('Owner-stated cost')).toBeInTheDocument()
    expect(screen.getByTestId('joint-cost')).toHaveTextContent('$41.8M')
    expect(screen.getByTestId('savings')).toHaveTextContent('$400K')

    const splits = screen.getByRole('table', { name: 'Cost splits' })
    const even = within(splits).getByText('50/50').closest('tr')!
    expect(within(even).getByText('fails')).toBeInTheDocument()
    const best = within(splits).getByText('Equal savings').closest('tr')!
    expect(best).toHaveClass('recommended')
    expect(within(best).getByText('passes')).toBeInTheDocument()
    expect(screen.getByTestId('recommended-reason')).toHaveTextContent('evenly')
  })

  it('recalculates with the planner inputs', async () => {
    const onAllocate = vi.fn().mockResolvedValue(allocation())
    render(<CostPanel pair={pair()} onAllocate={onAllocate} />)
    await screen.findByRole('table', { name: 'Cost splits' })
    await userEvent.click(screen.getByText('Allocation inputs'))
    const form = screen.getByRole('form', { name: 'Allocation inputs' })
    await userEvent.type(within(form).getByLabelText('Joint project cost ($M)'), '35')
    await userEvent.type(within(form).getByLabelText('Keystone Electric: Quantified benefit ($M)'), '12')
    await userEvent.type(within(form).getByLabelText('Chesapeake Power: Quantified benefit ($M)'), '30')
    await userEvent.type(within(form).getByLabelText(/Shareable share/), '40')
    await userEvent.click(within(form).getByRole('button', { name: 'Recalculate' }))
    expect(onAllocate).toHaveBeenLastCalledWith(expect.objectContaining({ id: '1-2' }), {
      joint_cost_musd: 35,
      benefit_a_musd: 12,
      benefit_b_musd: 30,
      shareable_fraction: 0.4,
    })
  })

  it('says why there is no split when a project cannot be priced', async () => {
    const unpriced = allocation({
      available: false,
      reason: 'Generation plant cost belongs to the developer.',
      estimate_b: estimate({ project_id: 2, available: false, central: null,
                             reason: 'Generation plant cost belongs to the developer.' }),
      splits: [],
    })
    render(<CostPanel pair={pair()} onAllocate={vi.fn().mockResolvedValue(unpriced)} />)
    expect(await screen.findByTestId('allocation-unavailable')).toHaveTextContent('Generation')
    expect(screen.queryByRole('table', { name: 'Cost splits' })).toBeNull()
  })

  it('saves a project\'s cost inputs to the project', async () => {
    const onPatch = vi.fn().mockResolvedValue({})
    render(
      <CostPanel
        pair={pair()}
        onAllocate={vi.fn().mockResolvedValue(allocation())}
        onPatchProject={onPatch}
      />,
    )
    await screen.findByRole('table', { name: 'Cost splits' })
    await userEvent.click(screen.getByText('Project cost inputs'))
    const form = screen.getByRole('form', { name: 'Cost inputs for Hanover breakers' })
    await userEvent.selectOptions(within(form).getByLabelText('Scope'), 'transformer')
    await userEvent.type(within(form).getByLabelText('Stated cost ($M)'), '6.5')
    await userEvent.type(within(form).getByLabelText('Cost year'), '2025')
    await userEvent.click(within(form).getByRole('button', { name: 'Save to project' }))
    expect(onPatch).toHaveBeenCalledWith(1, {
      cost_scope: 'transformer',
      length_mi: null,
      stated_cost_musd: 6.5,
      cost_year: 2025,
    })
  })
})

describe('money', () => {
  it('formats $M at a readable precision', () => {
    expect(money(0.85)).toBe('$850K')
    expect(money(12.34)).toBe('$12.3M')
    expect(money(240.4)).toBe('$240M')
    expect(money(1250)).toBe('$1.25B')
    expect(money(-5)).toBe('−$5.0M')
    expect(money(null)).toBe('—')
  })
})
