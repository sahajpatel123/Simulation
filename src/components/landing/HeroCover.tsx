'use client'

import { useEffect, useRef, useState } from 'react'
import { AnimatePresence, motion, useScroll, useTransform } from 'framer-motion'
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

function useLiveClock() {
  const [now, setNow] = useState<Date | null>(null)
  useEffect(() => {
    setNow(new Date())
    const id = setInterval(() => setNow(new Date()), 1000)
    return () => clearInterval(id)
  }, [])
  return now
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
  const ref = useRef<HTMLDivElement>(null)
  const word = useRotating()
  const now = useLiveClock()

  /* Scroll parallax — the cover lifts and dims as you leave it behind. */
  const { scrollYProgress } = useScroll({
    target: ref,
    offset: ['start start', 'end start'],
  })
  const y = useTransform(scrollYProgress, [0, 1], ['0%', '-8%'])
  const dim = useTransform(scrollYProgress, [0, 1], [1, 0.55])

  /* Cursor-tracked warm spotlight. */
  const [spot, setSpot] = useState<{ x: number; y: number } | null>(null)
  const onMove = (e: React.MouseEvent<HTMLDivElement>) => {
    const r = (e.currentTarget as HTMLDivElement).getBoundingClientRect()
    setSpot({ x: e.clientX - r.left, y: e.clientY - r.top })
  }
  const onLeave = () => setSpot(null)

  const dateLabel = now
    ? now.toLocaleDateString('en-GB', {
        weekday: 'long',
        day: '2-digit',
        month: 'long',
        year: 'numeric',
      })
    : '—'
  const timeLabel = now
    ? now.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', hour12: false })
    : '—'

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

      <motion.div
        style={{ y, opacity: dim }}
      >
        {/* ── masthead strip ─────────────────────────────────── */}
        <motion.div
          initial={{ opacity: 0, y: 8 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.5 }}
          style={{
            display: 'grid',
            gridTemplateColumns: '1fr auto 1fr',
            alignItems: 'center',
            padding: '22px 48px 14px',
            fontSize: 10,
            letterSpacing: '0.24em',
            textTransform: 'uppercase',
            color: 'var(--ink-secondary)',
            fontWeight: 500,
          }}
        >
          <span style={{ justifySelf: 'start' }}>Vol. I — Issue 04</span>
          <span
            className="font-serif"
            style={{
              justifySelf: 'center',
              fontSize: 13,
              letterSpacing: 0,
              fontStyle: 'italic',
              fontWeight: 700,
              color: 'var(--ink)',
              textTransform: 'none',
            }}
          >
            The Simulation Broadsheet
          </span>
          <span
            style={{
              justifySelf: 'end',
              fontVariantNumeric: 'tabular-nums',
              color: 'var(--ink-tertiary)',
            }}
          >
            {dateLabel} · {timeLabel}
          </span>
        </motion.div>

        {/* Animated rules */}
        <motion.div
          initial={{ scaleX: 0 }}
          animate={{ scaleX: 1 }}
          transition={{ duration: 0.7, ease: [0.2, 0.7, 0.2, 1] }}
          style={{ height: 3, background: 'var(--ink)', transformOrigin: 'left' }}
        />
        <motion.div
          initial={{ scaleX: 0 }}
          animate={{ scaleX: 1 }}
          transition={{ duration: 0.9, ease: [0.2, 0.7, 0.2, 1], delay: 0.1 }}
          style={{ height: 0.5, background: 'var(--border-color)', transformOrigin: 'left' }}
        />

        {/* ── cover story ────────────────────────────────────── */}
        <div
          style={{
            position: 'relative',
            maxWidth: 1280,
            margin: '0 auto',
            padding: 'clamp(72px, 10vh, 120px) 48px clamp(56px, 9vh, 96px)',
          }}
        >
          {/* Red kicker */}
          <motion.div
            initial={{ opacity: 0, y: 10 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.5, delay: 0.15 }}
            style={{
              display: 'flex',
              alignItems: 'center',
              gap: 14,
              marginBottom: 36,
            }}
          >
            <span style={{ width: 32, height: 0.5, background: 'var(--red)' }} />
            <span
              style={{
                fontSize: 10,
                letterSpacing: '0.3em',
                textTransform: 'uppercase',
                color: 'var(--red)',
                fontWeight: 600,
              }}
            >
              Cover Story · The Simulation, on paper
            </span>
          </motion.div>

          {/* Headline */}
          <h1
            className="font-serif"
            style={{
              fontSize: 'clamp(64px, 11vw, 188px)',
              fontWeight: 900,
              lineHeight: 0.88,
              letterSpacing: '-0.045em',
              color: 'var(--ink)',
              margin: 0,
              maxWidth: '18ch',
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
            </motion.span>
            <br />
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

          {/* Lede + actions — one single line of calm */}
          <motion.div
            initial={{ opacity: 0, y: 16 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.7, delay: 0.9 }}
            style={{
              marginTop: 52,
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
            transition={{ duration: 0.7, delay: 1.1 }}
            style={{
              marginTop: 72,
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'space-between',
              gap: 24,
              paddingTop: 18,
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
      </motion.div>
    </section>
  )
}
