import { sourceLink } from '../lib/sourceLink'

interface Props {
  url: string | null
  page: number | null
}

/** Opens the source document at the project's page in a new tab (Req 12). */
export function SourceLink({ url, page }: Props) {
  const href = sourceLink(url, page)
  if (!href) return <span className="muted">no source</span>
  return (
    <a href={href} target="_blank" rel="noopener noreferrer" className="source-link">
      {page ? `Source p.${page}` : 'Source'} ↗
    </a>
  )
}
