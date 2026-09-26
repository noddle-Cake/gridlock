export const DEFAULT_CONFIDENCE_THRESHOLD = 0.7

/**
 * A project needs review when its confidence is at or below the threshold
 * (Requirements 3.3 and 13.1: "equal to or below the Confidence_Threshold").
 */
export function needsReview(confidence: number, threshold: number): boolean {
  return confidence <= threshold
}
