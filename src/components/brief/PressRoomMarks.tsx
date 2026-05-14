'use client'

import { useMemo } from 'react'

function rotationFor(seed: string, range = 3) {
  let h = 0
  for (let i = 0; i < seed.length; i++) {
    h = (h * 31 + seed.charCodeAt(i)) | 0
  }
  return ((h % (range * 200)) / 100) - range
}

/* ─── Refine / Suggest mark — right margin ───────────────── */

interface MarkProps {
  field: string
  label: string
  hint: string
  onClick: () => void
  delay: number
  visible: boolean
}

export function MarginMark({ field, label, hint, onClick, delay, visible }: MarkProps) {
  const rot = useMemo(() => rotationFor(field + label), [field, label])

  return (
    <button
      onClick={onClick}
      style={{
        background: 'transparent',
        border: 'none',
        cursor: 'pointer',
        padding: '6px 10px',
        textAlign: 'left',
        opacity: visible ? 1 : 0,
        transform: visible ? `translateY(0) rotate(${rot}deg)` : `translateY(-8px) rotate(${rot}deg)`,
        transition: `opacity 280ms ease ${delay}ms, transform 280ms ease ${delay}ms`,
        position: 'relative',
        display: 'block',
      }}
    >
      <span
        style={{
          display: 'block',
          fontFamily: 'var(--font-serif), serif',
          fontStyle: 'italic',
          fontWeight: 700,
          fontSize: 16,
          color: 'rgba(192,57,43,0.88)',
          letterSpacing: '0.01em',
          lineHeight: 1.1,
          marginBottom: 2,
        }}
      >
        {label}
      </span>
      <span
        style={{
          display: 'block',
          fontFamily: 'var(--font-serif), serif',
          fontStyle: 'italic',
          fontSize: 11,
          color: 'rgba(192,57,43,0.55)',
          lineHeight: 1.2,
        }}
      >
        {hint}
      </span>
      <svg
        width="60"
        height="6"
        viewBox="0 0 60 6"
        style={{ position: 'absolute', left: 6, bottom: -2, opacity: 0.7 }}
      >
        <path
          d="M 1 3 Q 15 1, 30 3 T 58 2"
          stroke="#c0392b"
          strokeWidth="1.2"
          fill="none"
          strokeLinecap="round"
          opacity="0.75"
        />
      </svg>
    </button>
  )
}

/* ─── Critique underline — wavy red path ────────────────── */

interface CritiqueUnderlineProps {
  visible: boolean
  delay: number
  onClick: () => void
}

export function CritiqueUnderline({ visible, delay, onClick }: CritiqueUnderlineProps) {
  return (
    <div
      onClick={onClick}
      style={{
        position: 'absolute',
        left: 0,
        right: 0,
        bottom: -2,
        height: 12,
        cursor: 'pointer',
        opacity: visible ? 1 : 0,
        transform: visible ? 'translateY(0)' : 'translateY(-4px)',
        transition: `opacity 320ms ease ${delay}ms, transform 320ms ease ${delay}ms`,
      }}
      title="Critique"
    >
      <svg width="100%" height="12" viewBox="0 0 400 12" preserveAspectRatio="none" style={{ overflow: 'visible' }}>
        <path
          d="M 2 6 Q 12 2, 22 6 T 42 6 T 62 6 T 82 6 T 102 6 T 122 6 T 142 6 T 162 6 T 182 6 T 202 6 T 222 6 T 242 6 T 262 6 T 282 6 T 302 6 T 322 6 T 342 6 T 362 6 T 382 6 T 398 6"
          stroke="#c0392b"
          strokeWidth="1.4"
          fill="none"
          strokeLinecap="round"
          opacity="0.78"
        />
        <circle cx="396" cy="6" r="2" fill="#c0392b" opacity="0.85" />
      </svg>
      <span
        style={{
          position: 'absolute',
          right: 0,
          top: -22,
          fontFamily: 'var(--font-serif), serif',
          fontStyle: 'italic',
          fontWeight: 700,
          fontSize: 13,
          color: 'rgba(192,57,43,0.88)',
          letterSpacing: '0.01em',
        }}
      >
        critique
      </span>
    </div>
  )
}
