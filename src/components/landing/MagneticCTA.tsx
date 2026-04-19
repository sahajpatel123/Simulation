'use client'

import { useRef, type CSSProperties, type ReactNode, type MouseEvent } from 'react'
import Link from 'next/link'

/**
 * Anchor that subtly pulls toward the cursor on hover, like a magnet.
 * Works with internal href (Next Link) or external/onClick.
 */
export default function MagneticCTA({
  href,
  onClick,
  children,
  style,
  strength = 0.25,
  magnetic = true,
}: {
  href?: string
  onClick?: () => void
  children: ReactNode
  style?: CSSProperties
  strength?: number
  /** When false, render a normal control with no cursor-follow translate. */
  magnetic?: boolean
}) {
  const ref = useRef<HTMLDivElement>(null)

  const inner = (
    <span
      style={{
        display: 'inline-flex',
        alignItems: 'center',
        gap: 10,
        ...style,
      }}
    >
      {children}
    </span>
  )

  if (!magnetic) {
    if (href) {
      return (
        <Link href={href} style={{ textDecoration: 'none' }}>
          {inner}
        </Link>
      )
    }
    return (
      <button
        type="button"
        onClick={onClick}
        style={{ background: 'none', border: 'none', padding: 0, cursor: 'pointer', font: 'inherit' }}
      >
        {inner}
      </button>
    )
  }

  const handle = (e: MouseEvent<HTMLSpanElement>) => {
    const el = ref.current
    if (!el) return
    const r = el.getBoundingClientRect()
    const x = e.clientX - (r.left + r.width / 2)
    const y = e.clientY - (r.top + r.height / 2)
    el.style.transform = `translate(${x * strength}px, ${y * strength}px)`
  }
  const reset = () => {
    if (ref.current) ref.current.style.transform = 'translate(0,0)'
  }

  return (
    <span
      onMouseMove={handle}
      onMouseLeave={reset}
      style={{ display: 'inline-block' }}
    >
      <div
        ref={ref}
        style={{ display: 'inline-block', transition: 'transform 220ms cubic-bezier(.2,.7,.2,1)' }}
      >
        {href ? (
          <Link href={href} style={{ textDecoration: 'none' }}>
            {inner}
          </Link>
        ) : (
          <button
            type="button"
            onClick={onClick}
            style={{ background: 'none', border: 'none', padding: 0, cursor: 'pointer', font: 'inherit' }}
          >
            {inner}
          </button>
        )}
      </div>
    </span>
  )
}
