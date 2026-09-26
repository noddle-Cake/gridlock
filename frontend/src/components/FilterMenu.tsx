import { type ReactNode, useEffect, useRef, useState } from 'react'

interface Props {
  label: ReactNode
  /** Highlights the chip when its filter differs from the default. */
  active?: boolean
  align?: 'left' | 'right'
  className?: string
  children: ReactNode
}

/**
 * A filter-bar chip that opens a dropdown. Built on <details> so the contents stay
 * mounted (and reachable by label) while closed; outside clicks and Escape close it.
 */
export function FilterMenu({ label, active = false, align = 'left', className, children }: Props) {
  const [open, setOpen] = useState(false)
  const ref = useRef<HTMLDetailsElement>(null)

  useEffect(() => {
    if (!open) return
    function onPointer(e: PointerEvent) {
      if (!ref.current?.contains(e.target as Node)) setOpen(false)
    }
    function onKey(e: KeyboardEvent) {
      if (e.key === 'Escape') setOpen(false)
    }
    document.addEventListener('pointerdown', onPointer)
    document.addEventListener('keydown', onKey)
    return () => {
      document.removeEventListener('pointerdown', onPointer)
      document.removeEventListener('keydown', onKey)
    }
  }, [open])

  return (
    <details
      ref={ref}
      className={`filter-menu${active ? ' active' : ''}${className ? ` ${className}` : ''}`}
      open={open}
      onToggle={(e) => setOpen(e.currentTarget.open)}
    >
      <summary className="chip">
        {label}
        <svg className="caret" width="10" height="10" viewBox="0 0 10 10" aria-hidden="true">
          <path d="M2 3.5 5 6.5 8 3.5" fill="none" stroke="currentColor" strokeWidth="1.5" />
        </svg>
      </summary>
      <div className={`popover popover-${align}`}>{children}</div>
    </details>
  )
}
