'use client'

import { useEffect, useRef, useState } from 'react'
import { AnimatePresence, motion } from 'framer-motion'
import { ArrowRight } from 'lucide-react'
import MagneticCTA from './MagneticCTA'

const ROTATING = ['startup', 'product', 'idea', 'launch', 'pricing', 'pivot']

function useRotating(intervalMs = 2600) {
  const [i, setI] = useState(0)
  useEffect(() => {
    const t = setInterval(() => setI((p) => (p + 1) % ROTATING.length), intervalMs)
    return () => clearInterval(t)
  }, [intervalMs])
  return ROTATING[i]
}

/**
 * A quiet broadsheet cover.
 *   - One huge line of type that rotates its last word.
 *   - Two thin rules (masthead + baseline) that draw in on mount.
 *   - Subtle parallax on scroll, and a cursor-tracked spotlight
 *     that lives behind the headline without touching legibility.
 */
export default function HeroCover({
  onSignup,
  onHowItWorks,
}: {
  onSignup: () => void
  onHowItWorks: () => void
}) {
  const ref = useRef<HTMLElement>(null)
  const word = useRotating()

  /**
   * Manual scroll progress (same intent as Motion's useScroll target offsets).
   * Avoids useScroll({ target }) which throws in production if the ref is not
   * yet hydrated when Motion's internal useEffect runs (Next.js + Strict Mode).
   */
  const [leaveProgress, setLeaveProgress] = useState(0)
  useEffect(() => {
    const el = ref.current
    if (!el) return

    const update = () => {
      const rect = el.getBoundingClientRect()
      const h = Math.max(rect.height, 1)
      /* 0 = hero top at viewport top; 1 = hero scrolled up by one full height */
      const p = Math.min(1, Math.max(0, -rect.top / h))
      setLeaveProgress(p)
    }

    update()
    window.addEventListener('scroll', update, { passive: true })
    window.addEventListener('resize', update)
    return () => {
      window.removeEventListener('scroll', update)
      window.removeEventListener('resize', update)
    }
  }, [])

  /* Cursor-tracked warm spotlight. */
  const [spot, setSpot] = useState<{ x: number; y: number } | null>(null)
  const onMove = (e: React.MouseEvent<HTMLDivElement>) => {
    const r = (e.currentTarget as HTMLDivElement).getBoundingClientRect()
    setSpot({ x: e.clientX - r.left, y: e.clientY - r.top })
  }
  const onLeave = () => setSpot(null)

  return (
    <section
      ref={ref}
      onMouseMove={onMove}
      onMouseLeave={onLeave}
      style={{
        position: 'relative',
        borderBottom: '0.5px solid var(--border-color)',
        background: 'var(--paper)',
        overflow: 'hidden',
      }}
    >
      {/* Warm spotlight behind the cover. */}
      <motion.div
        aria-hidden
        animate={spot ? { opacity: 1 } : { opacity: 0 }}
        transition={{ duration: 0.4 }}
        style={{
          position: 'absolute',
          inset: 0,
          pointerEvents: 'none',
          background: spot
            ? `radial-gradient(380px 380px at ${spot.x}px ${spot.y}px, rgba(192,57,43,0.08), transparent 70%)`
            : 'transparent',
        }}
      />

      <div
        style={{
          transform: `translateY(${-8 * leaveProgress}%)`,
          opacity: 1 - 0.45 * leaveProgress,
          willChange: 'transform, opacity',
        }}
      >
        {/* First screen = air → headline; folio lives in sticky masthead */}
        <div
          style={{
            minHeight: 'calc(100svh - 96px)',
            display: 'flex',
            flexDirection: 'column',
            boxSizing: 'border-box',
          }}
        >
          <div
            style={{
              position: 'relative',
              maxWidth: 1280,
              margin: '0 auto',
              width: '100%',
              flex: '0 0 auto',
              padding: 'clamp(28px, 8vh, 80px) 48px 0',
            }}
          >
            {/* Headline */}
            <h1
              className="font-serif"
              style={{
                fontSize: 'clamp(58px, 14.2vw, 168px)',
                fontWeight: 900,
                lineHeight: 0.88,
                letterSpacing: '-0.045em',
                color: 'var(--ink)',
                margin: 0,
                maxWidth: 'min(100%, 13ch)',
              }}
            >
              <motion.span
                initial={{ y: '0.45em', opacity: 0 }}
                animate={{ y: 0, opacity: 1 }}
                transition={{ duration: 0.8, delay: 0.2, ease: [0.2, 0.7, 0.2, 1] }}
                style={{ display: 'inline-block' }}
              >
                Know
              </motion.span>{' '}
              <motion.span
                initial={{ y: '0.45em', opacity: 0 }}
                animate={{ y: 0, opacity: 1 }}
                transition={{ duration: 0.8, delay: 0.32, ease: [0.2, 0.7, 0.2, 1] }}
                style={{ display: 'inline-block' }}
              >
                before
              </motion.span>{' '}
              <motion.span
                initial={{ y: '0.45em', opacity: 0 }}
                animate={{ y: 0, opacity: 1 }}
                transition={{ duration: 0.8, delay: 0.44, ease: [0.2, 0.7, 0.2, 1] }}
                style={{ display: 'inline-block' }}
              >
                you
              </motion.span>{' '}
              <motion.span
                initial={{ y: '0.45em', opacity: 0 }}
                animate={{ y: 0, opacity: 1 }}
                transition={{ duration: 0.8, delay: 0.56, ease: [0.2, 0.7, 0.2, 1] }}
                style={{ display: 'inline-block' }}
              >
                build your
              </motion.span>{' '}
              {/* Rotating accent word with a soft ink bloom behind it */}
              <span
                style={{
                  position: 'relative',
                  display: 'inline-block',
                  perspective: 800,
                  verticalAlign: 'baseline',
                }}
              >
                <AnimatePresence mode="wait">
                  <motion.span
                    key={word}
                    initial={{ y: '0.5em', opacity: 0, rotateX: 60 }}
                    animate={{ y: 0, opacity: 1, rotateX: 0 }}
                    exit={{ y: '-0.45em', opacity: 0, rotateX: -60 }}
                    transition={{ duration: 0.55, ease: [0.76, 0, 0.24, 1] }}
                    style={{
                      display: 'inline-block',
                      fontStyle: 'italic',
                      color: 'var(--red)',
                      position: 'relative',
                      transformOrigin: 'center bottom',
                    }}
                  >
                    <span
                      aria-hidden
                      style={{
                        position: 'absolute',
                        inset: '-0.05em -0.08em -0.1em -0.08em',
                        background:
                          'radial-gradient(closest-side, rgba(192,57,43,0.12), transparent 70%)',
                        filter: 'blur(6px)',
                        zIndex: -1,
                      }}
                    />
                    {word}
                  </motion.span>
                </AnimatePresence>
                <motion.span
                  initial={{ scaleX: 0, opacity: 0 }}
                  animate={{ scaleX: 1, opacity: 0.8 }}
                  transition={{ duration: 0.6, delay: 0.7 }}
                  style={{
                    display: 'block',
                    height: 2,
                    marginTop: 2,
                    background: 'var(--red)',
                    transformOrigin: 'left',
                  }}
                />
              </span>
              <motion.span
                initial={{ opacity: 0 }}
                animate={{ opacity: 1 }}
                transition={{ duration: 0.6, delay: 0.85 }}
                style={{ color: 'var(--ink-tertiary)' }}
              >
                .
              </motion.span>
            </h1>
          </div>

          {/* Absorbs any slack so the fold lands near the viewport bottom */}
          <div aria-hidden style={{ flex: '1 1 auto', minHeight: 0 }} />
        </div>

        {/* ── Below the fold: lede, CTAs, meta ───────────────── */}
        <div
          style={{
            position: 'relative',
            maxWidth: 1280,
            margin: '0 auto',
            padding: 'clamp(32px, 5vh, 56px) 48px clamp(48px, 7.5vh, 88px)',
          }}
        >
          {/* Lede + actions */}
          <motion.div
            initial={{ opacity: 0, y: 16 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.7, delay: 0.2 }}
            style={{
              display: 'grid',
              gridTemplateColumns: 'minmax(0, 1.2fr) auto',
              alignItems: 'end',
              gap: 48,
            }}
          >
            <p
              className="font-serif"
              style={{
                fontSize: 'clamp(17px, 1.4vw, 22px)',
                lineHeight: 1.6,
                color: 'var(--ink)',
                fontWeight: 300,
                letterSpacing: '-0.005em',
                maxWidth: '56ch',
                margin: 0,
              }}
            >
              A broadsheet that simulates reality before you commit to it.{' '}
              <span style={{ color: 'var(--ink-secondary)' }}>
                One idea, thousands of synthetic readers, the autopsy printed in
                under two minutes.
              </span>
            </p>

            <div
              style={{
                display: 'flex',
                alignItems: 'center',
                gap: 28,
                justifySelf: 'end',
                flexWrap: 'wrap',
              }}
            >
              <MagneticCTA
                magnetic={false}
                onClick={onSignup}
                style={{
                  background: 'var(--ink)',
                  color: 'var(--paper)',
                  padding: '16px 30px',
                  fontSize: 11,
                  letterSpacing: '0.18em',
                  textTransform: 'uppercase',
                  fontWeight: 600,
                }}
              >
                Validate your idea <ArrowRight size={12} />
              </MagneticCTA>
              <button
                type="button"
                onClick={onHowItWorks}
                style={{
                  background: 'none',
                  border: 'none',
                  padding: 0,
                  cursor: 'pointer',
                  fontFamily: 'inherit',
                  fontSize: 11,
                  letterSpacing: '0.2em',
                  textTransform: 'uppercase',
                  color: 'var(--ink-secondary)',
                  borderBottom: '0.5px solid var(--border-strong)',
                  paddingBottom: 4,
                  transition: 'color 180ms ease, border-color 180ms ease',
                }}
                onMouseEnter={(e) => {
                  e.currentTarget.style.color = 'var(--red)'
                  e.currentTarget.style.borderColor = 'var(--red)'
                }}
                onMouseLeave={(e) => {
                  e.currentTarget.style.color = 'var(--ink-secondary)'
                  e.currentTarget.style.borderColor = 'var(--border-strong)'
                }}
              >
                Read how it works →
              </button>
            </div>
          </motion.div>

          {/* Quiet meta row at the baseline of the cover */}
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            transition={{ duration: 0.7, delay: 0.35 }}
            style={{
              marginTop: 56,
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'space-between',
              gap: 24,
              paddingTop: 16,
              borderTop: '0.5px solid var(--border-color)',
              fontSize: 10,
              letterSpacing: '0.22em',
              textTransform: 'uppercase',
              color: 'var(--ink-tertiary)',
              fontWeight: 500,
            }}
          >
            <span>243 founders · 1.4M scenarios · filed quarterly</span>
            <span style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
              <span
                aria-hidden
                style={{
                  width: 6,
                  height: 6,
                  borderRadius: '50%',
                  background: 'var(--red)',
                  display: 'inline-block',
                  animation: 'pulse-red 1.6s ease-in-out infinite',
                }}
              />
              Press is live
            </span>
          </motion.div>
        </div>
      </div>
    </section>
  )
}
