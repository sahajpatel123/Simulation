'use client'

import { useCallback, useEffect, useRef, useState } from 'react'

type Plate = {
  n: string
  kicker: string
  title: string
  body: string
}

/** Piecewise linear map through (x0,y0)-(x1,y1)-(x2,y2) for x in [x0,x2]. */
function triLerp(x: number, x0: number, x1: number, x2: number, y0: number, y1: number, y2: number) {
  if (x <= x0) return y0
  if (x >= x2) return y2
  if (x <= x1) return y0 + ((x - x0) / Math.max(1e-6, x1 - x0)) * (y1 - y0)
  return y1 + ((x - x1) / Math.max(1e-6, x2 - x1)) * (y2 - y1)
}

/**
 * Sticky, scroll-driven plate advance. Uses manual scroll progress instead of
 * Motion's `useScroll({ target })`, which throws in production if the ref is
 * not hydrated when Motion's internal effect runs (Next.js + Strict Mode).
 */
export default function ProcessReel({ plates }: { plates: readonly Plate[] }) {
  const trackRef = useRef<HTMLDivElement>(null)
  const [progress, setProgress] = useState(0)

  const updateProgress = useCallback(() => {
    const el = trackRef.current
    if (!el) return
    const rect = el.getBoundingClientRect()
    const scrollTop = window.scrollY || document.documentElement.scrollTop
    const elementTop = scrollTop + rect.top
    const range = Math.max(1, el.offsetHeight - window.innerHeight)
    const p = Math.min(1, Math.max(0, (scrollTop - elementTop) / range))
    setProgress(p)
  }, [])

  useEffect(() => {
    updateProgress()
    window.addEventListener('scroll', updateProgress, { passive: true })
    window.addEventListener('resize', updateProgress)
    return () => {
      window.removeEventListener('scroll', updateProgress)
      window.removeEventListener('resize', updateProgress)
    }
  }, [updateProgress])

  const n = plates.length
  const xPercent = -(n - 1) * 100 * progress

  return (
    <section
      id="how"
      style={{
        borderBottom: '0.5px solid var(--border-color)',
        background: 'var(--paper)',
        position: 'relative',
      }}
    >
      <div
        style={{
          maxWidth: 1280,
          margin: '0 auto',
          padding: '96px 48px 0',
        }}
      >
        <div style={{ display: 'flex', alignItems: 'center', gap: 14, marginBottom: 24 }}>
          <span style={{ width: 28, height: 0.5, background: 'var(--red)' }} />
          <span
            style={{
              fontSize: 10,
              letterSpacing: '0.3em',
              textTransform: 'uppercase',
              color: 'var(--red)',
              fontWeight: 600,
            }}
          >
            The Process · On three plates
          </span>
        </div>
        <h2
          className="font-serif"
          style={{
            fontSize: 'clamp(36px, 4vw, 60px)',
            fontWeight: 900,
            fontStyle: 'italic',
            color: 'var(--ink)',
            lineHeight: 1.02,
            letterSpacing: '-0.035em',
            margin: 0,
            maxWidth: 900,
          }}
        >
          Three plates, three impressions,{' '}
          <span style={{ color: 'var(--red)' }}>one</span> certainty.
        </h2>
      </div>

      <div ref={trackRef} style={{ height: `${plates.length * 100}vh`, position: 'relative' }}>
        <div
          style={{
            position: 'sticky',
            top: 0,
            height: '100vh',
            display: 'flex',
            alignItems: 'center',
            overflow: 'hidden',
          }}
        >
          <div
            style={{
              display: 'flex',
              width: `${plates.length * 100}%`,
              transform: `translateX(${xPercent}%)`,
              willChange: 'transform',
            }}
          >
            {plates.map((p, i) => (
              <Plate key={p.n} plate={p} index={i} total={plates.length} progress={progress} />
            ))}
          </div>

          <div
            style={{
              position: 'absolute',
              bottom: 48,
              left: 0,
              right: 0,
              display: 'flex',
              justifyContent: 'center',
              pointerEvents: 'none',
            }}
          >
            <Ledger plates={plates} progress={progress} />
          </div>
        </div>
      </div>
    </section>
  )
}

function Plate({
  plate,
  index,
  total,
  progress,
}: {
  plate: Plate
  index: number
  total: number
  progress: number
}) {
  const center = index / Math.max(1, total - 1)
  const span = 1 / Math.max(1, total - 1)
  const y = triLerp(progress, center - span * 0.6, center, center + span * 0.6, 40, 0, -40)
  const opacity = triLerp(progress, center - span * 0.7, center, center + span * 0.7, 0.3, 1, 0.3)

  return (
    <div
      style={{
        flex: `0 0 100%`,
        padding: '0 clamp(48px, 8vw, 140px)',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
      }}
    >
      <article
        style={{
          transform: `translateY(${y}px)`,
          opacity,
          maxWidth: 1040,
          width: '100%',
          display: 'grid',
          gridTemplateColumns: '220px 1fr',
          gap: 64,
          alignItems: 'center',
          background: 'var(--paper-dark)',
          border: '0.5px solid var(--ink)',
          padding: 'clamp(40px, 6vw, 72px)',
          position: 'relative',
          boxShadow: '12px 12px 0 var(--ink)',
          willChange: 'transform, opacity',
        }}
      >
        <span
          aria-hidden
          style={{
            position: 'absolute',
            top: -1,
            left: -1,
            width: 72,
            height: 4,
            background: 'var(--red)',
          }}
        />

        <div style={{ borderRight: '0.5px solid var(--border-color)', paddingRight: 40 }}>
          <div
            className="font-serif numeral"
            style={{
              fontSize: 'clamp(100px, 12vw, 176px)',
              lineHeight: 0.9,
              letterSpacing: '-0.06em',
              color: 'var(--ink)',
              fontStyle: 'italic',
            }}
          >
            {plate.n}
          </div>
          <div
            style={{
              marginTop: 18,
              fontSize: 10,
              letterSpacing: '0.3em',
              textTransform: 'uppercase',
              color: 'var(--red)',
              fontWeight: 600,
            }}
          >
            Plate · {index + 1} of {total}
          </div>
        </div>

        <div>
          <div
            style={{
              fontSize: 11,
              letterSpacing: '0.24em',
              textTransform: 'uppercase',
              color: 'var(--ink-secondary)',
              fontWeight: 600,
              marginBottom: 20,
            }}
          >
            {plate.kicker}
          </div>
          <h3
            className="font-serif"
            style={{
              fontSize: 'clamp(28px, 2.8vw, 44px)',
              fontWeight: 800,
              fontStyle: 'italic',
              color: 'var(--ink)',
              lineHeight: 1.15,
              letterSpacing: '-0.02em',
              margin: 0,
              marginBottom: 20,
            }}
          >
            {plate.title}
          </h3>
          <div style={{ height: 2, width: 28, background: 'var(--red)', marginBottom: 22 }} />
          <p
            style={{
              fontSize: 16,
              color: 'var(--ink)',
              lineHeight: 1.8,
              fontWeight: 300,
              maxWidth: 560,
              margin: 0,
            }}
          >
            {plate.body}
          </p>
        </div>
      </article>
    </div>
  )
}

function Ledger({
  plates,
  progress,
}: {
  plates: readonly Plate[]
  progress: number
}) {
  return (
    <div
      style={{
        display: 'flex',
        gap: 48,
        padding: '14px 28px',
        background: 'var(--paper)',
        border: '0.5px solid var(--border-color)',
      }}
    >
      {plates.map((p, i) => (
        <LedgerItem key={p.n} plate={p} index={i} total={plates.length} progress={progress} />
      ))}
    </div>
  )
}

function LedgerItem({
  plate,
  index,
  total,
  progress,
}: {
  plate: Plate
  index: number
  total: number
  progress: number
}) {
  const center = index / Math.max(1, total - 1)
  const span = 1 / Math.max(1, total - 1)
  const active = triLerp(progress, center - span * 0.5, center, center + span * 0.5, 0, 1, 0)
  const labelOpacity = 0.35 + active * 0.65

  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
      <span
        style={{
          display: 'inline-block',
          width: 8,
          height: 8,
          borderRadius: '50%',
          background: 'var(--red)',
          transform: `scale(${0.35 + active * 0.65})`,
          transformOrigin: 'center',
        }}
      />
      <span
        style={{
          fontSize: 10,
          letterSpacing: '0.24em',
          textTransform: 'uppercase',
          color: 'var(--ink-secondary)',
          opacity: labelOpacity,
          fontWeight: 600,
          fontVariantNumeric: 'tabular-nums',
        }}
      >
        {String(index + 1).padStart(2, '0')} — {plate.kicker}
      </span>
    </div>
  )
}
