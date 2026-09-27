import type { CoordinationPair } from '../types'

/**
 * The company a signed-in account works for, from its email domain. GridMerge is used by
 * planners at a utility, and their own company is what every view should be read against.
 * Add a domain here to onboard another client utility.
 */
const EMAIL_DOMAIN_COMPANY: Record<string, string> = {
  'fpl.com': 'Florida Power & Light',
}

/** How planners refer to their company in labels ("Only FPL's opportunities"). */
const SHORT_NAMES: Record<string, string> = {
  'Florida Power & Light': 'FPL',
}

export function shortName(company: string): string {
  return SHORT_NAMES[company] ?? company
}

// Whether the list shows only the planner's own company's pairs or everyone's. Remembered on
// this device so a demo left on "All companies" stays there across reloads; per-viewer
// convenience only, so with storage unavailable it falls back to the company's own pairs.
const SCOPE_KEY = 'gridmerge:pair-scope'

export function loadOnlyOwn(): boolean {
  try {
    return localStorage.getItem(SCOPE_KEY) !== 'all'
  } catch {
    return true
  }
}

export function saveOnlyOwn(on: boolean): void {
  try {
    if (on) localStorage.removeItem(SCOPE_KEY)
    else localStorage.setItem(SCOPE_KEY, 'all')
  } catch {
    /* storage unavailable */
  }
}

/** The account's company, if its email domain is known and the company has projects loaded. */
export function accountCompany(
  username: string | null | undefined,
  utilities: readonly string[],
): string | null {
  const domain = username?.split('@')[1]?.trim().toLowerCase()
  const company = domain ? EMAIL_DOMAIN_COMPANY[domain] : undefined
  return company && utilities.includes(company) ? company : null
}

/** Whether a (possibly jointly owned, "A / B") utility includes `company`. */
function includes(utility: string, company: string): boolean {
  return utility === company || utility.split(' / ').includes(company)
}

/** Whether one of the pair's projects belongs to `company` (alone or jointly). */
export function involves(pair: CoordinationPair, company: string): boolean {
  return includes(pair.project_a.utility, company) || includes(pair.project_b.utility, company)
}

/**
 * The companies `company` shares coordination pairs with, most pairs first (ties
 * alphabetical): the neighbours its planners would actually call.
 */
export function pairPartners(pairs: readonly CoordinationPair[], company: string): string[] {
  const counts = new Map<string, number>()
  for (const { project_a: a, project_b: b } of pairs) {
    const other = includes(a.utility, company)
      ? b.utility
      : includes(b.utility, company)
        ? a.utility
        : null
    if (other && !includes(other, company)) counts.set(other, (counts.get(other) ?? 0) + 1)
  }
  return [...counts]
    .sort((x, y) => y[1] - x[1] || x[0].localeCompare(y[0]))
    .map(([u]) => u)
}
