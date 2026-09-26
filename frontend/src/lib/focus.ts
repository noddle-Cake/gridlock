// The Sperry Tech challenge's example pair: neighbours across the Savannah River.
export const CHALLENGE_UTILITIES = ['Dominion Energy South Carolina', 'Georgia Power'] as const

/**
 * Utilities to hide so only `focus` shows, or null when not every focus utility is loaded
 * (nothing to focus on; keep showing everything).
 */
export function focusHidden(
  utilities: readonly string[],
  focus: readonly string[] = CHALLENGE_UTILITIES,
): Set<string> | null {
  if (!focus.every((u) => utilities.includes(u))) return null
  return new Set(utilities.filter((u) => !focus.includes(u)))
}
