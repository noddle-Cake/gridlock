/**
 * Link to a project's source document at its page (Req 12.1). PDF viewers honor
 * the `#page=N` fragment; any existing fragment on the URL is replaced.
 */
export function sourceLink(sourceUrl: string | null, sourcePage: number | null): string | null {
  if (!sourceUrl) return null
  const base = sourceUrl.split('#')[0]
  if (sourcePage == null || !Number.isInteger(sourcePage) || sourcePage < 1) return base
  return `${base}#page=${sourcePage}`
}
