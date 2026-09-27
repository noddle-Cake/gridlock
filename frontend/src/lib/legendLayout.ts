/**
 * Smallest map, in px, that the open "Color by" card (about 260 × 330 with the layers
 * card and "Fit all" under it) can sit on without hiding a big share of the projects.
 * The stacked tablet layout (≈860 × 495 map) falls short on height; a squeezed split
 * layout falls short on width; a desktop split (≈810 × 790) clears both.
 */
export const LEGEND_OPEN_MIN = { width: 640, height: 600 } as const

/**
 * Whether the colour legend should start open on a map of this size. An unmeasured map
 * (0 × 0, e.g. not laid out yet) keeps the default open card.
 */
export function legendStartsOpen(width: number, height: number): boolean {
  if (width <= 0 || height <= 0) return true
  return width >= LEGEND_OPEN_MIN.width && height >= LEGEND_OPEN_MIN.height
}
