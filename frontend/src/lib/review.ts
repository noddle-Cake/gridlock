import type { Project } from '../types'

export const DEFAULT_CONFIDENCE_THRESHOLD = 0.7

/**
 * A project needs review when its confidence is at or below the threshold
 * (Requirements 3.3 and 13.1: "equal to or below the Confidence_Threshold").
 */
export function needsReview(confidence: number, threshold: number): boolean {
  return confidence <= threshold
}

/**
 * Whether a project belongs in the Review queue: something a reviewer can fix here (a
 * low-confidence or unplaced extraction) that hasn't been marked reviewed.
 *
 * Unverified corporate ownership isn't: it comes from the ownership audit
 * (backend/app/data/company_ownership.csv), not from edits here, and covers most of the
 * EIA-860M project companies. Those projects stay out of the queue; their pairs carry an
 * "ownership unverified" label instead.
 */
export function inReviewQueue(
  p: Pick<Project, 'reviewed' | 'confidence' | 'requires_review'>,
  threshold: number,
): boolean {
  return !p.reviewed && (needsReview(p.confidence, threshold) || p.requires_review)
}
