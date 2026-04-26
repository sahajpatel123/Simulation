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
 * Landing hero — matches the editorial “plate” reference:
 * rounded inset card, four tight lines with staggered “you”, red italic last word + rule + dot.
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
          transform: `translateY(${-6 * leaveProgress}%)`,
          opacity: 1 - 0.12 * leaveProgress,
          willChange: 'transform, opacity',
        }}
      >
        {/* Rounded “plate” + reference composition (tight stack, staggered lines, huge type) */}
        <div
          style={{
            margin: 'clamp(8px, 1.2vw, 22px) clamp(10px, 2vw, 32px) clamp(8px, 1.2vw, 22px)',
            borderRadius: 18,
            border: '0.5px solid rgba(26, 23, 20, 0.08)',
            background: 'linear-gradient(165deg, #faf7f0 0%, var(--paper) 38%, var(--paper) 100%)',
            boxShadow:
              '0 1px 0 rgba(255,255,255,0.65) inset, 0 28px 70px -36px rgba(26,23,20,0.14), 0 12px 32px -28px rgba(45,69,86,0.08)',
            overflow: 'hidden',
            minHeight: 'calc(100svh - 96px - clamp(16px, 2.4vw, 28px))',
            display: 'flex',
            flexDirection: 'column',
            boxSizing: 'border-box',
          }}
        >
          <div
            style={{
              flex: '1 1 auto',
              minHeight: 0,
              display: 'flex',
              flexDirection: 'column',
              justifyContent: 'center',
              padding: 'clamp(28px, 5vh, 72px) clamp(22px, 5vw, 96px)',
            }}
          >
            <div
              style={{
                position: 'relative',
                maxWidth: 1320,
                margin: '0 auto',
                width: '100%',
                isolation: 'isolate',
              }}
            >
              <div
                aria-hidden
                style={{
                  position: 'absolute',
                  zIndex: 0,
                  inset: '-8% -6% -12% -6%',
                  pointerEvents: 'none',
                  background: `
                    radial-gradient(ellipse 68% 56% at 48% 46%,
                      rgba(255, 250, 242, 0.75) 0%,
                      rgba(242, 236, 224, 0.28) 52%,
                      transparent 74%)
                  `,
                }}
              />

              <div
                style={{
                  position: 'relative',
                  zIndex: 2,
                  display: 'flex',
                  width: '100%',
                  justifyContent: 'center',
                }}
              >
                <h1
                  className="font-serif"
                  style={{
                    fontSize: 'clamp(56px, min(13.8vw, 20svh), 176px)',
                    fontWeight: 900,
                    lineHeight: 0.84,
                    letterSpacing: '-0.048em',
                    color: 'var(--ink)',
                    margin: 0,
                    maxWidth: '100%',
                    textAlign: 'left',
                  }}
                >
                  <motion.span
                    initial={{ y: '0.35em', opacity: 0 }}
                    animate={{ y: 0, opacity: 1 }}
                    transition={{ duration: 0.75, delay: 0.18, ease: [0.2, 0.72, 0.2, 1] }}
                    style={{ display: 'block' }}
                  >
                    Know before
                  </motion.span>
                  <motion.span
                    initial={{ y: '0.35em', opacity: 0 }}
                    animate={{ y: 0, opacity: 1 }}
                    transition={{ duration: 0.75, delay: 0.28, ease: [0.2, 0.72, 0.2, 1] }}
                    style={{
                      display: 'block',
                      marginTop: '-0.035em',
                      paddingLeft: 'clamp(2.25rem, 15vw, 9rem)',
                    }}
                  >
                    you
                  </motion.span>
                  <motion.span
                    initial={{ y: '0.35em', opacity: 0 }}
                    animate={{ y: 0, opacity: 1 }}
                    transition={{ duration: 0.75, delay: 0.38, ease: [0.2, 0.72, 0.2, 1] }}
                    style={{ display: 'block', marginTop: '-0.04em' }}
                  >
                    build your
                  </motion.span>
                  <motion.span
                    initial={{ y: '0.35em', opacity: 0 }}
                    animate={{ y: 0, opacity: 1 }}
                    transition={{ duration: 0.75, delay: 0.48, ease: [0.2, 0.72, 0.2, 1] }}
                    style={{
                      display: 'flex',
                      flexDirection: 'row',
                      flexWrap: 'nowrap',
                      alignItems: 'flex-end',
                      gap: '0.12em',
                      marginTop: '-0.04em',
                    }}
                  >
                    <span
                      style={{
                        position: 'relative',
                        zIndex: 2,
                        display: 'inline-flex',
                        flexDirection: 'column',
                        alignItems: 'flex-start',
                      }}
                    >
                      <AnimatePresence mode="wait">
                        <motion.span
                          key={word}
                          initial={{ opacity: 0, y: 10 }}
                          animate={{ opacity: 1, y: 0 }}
                          exit={{ opacity: 0, y: -8 }}
                          transition={{ duration: 0.22, ease: 'easeOut' }}
                          style={{
                            display: 'inline-block',
                            fontStyle: 'italic',
                            color: 'var(--red)',
                            WebkitTextFillColor: 'var(--red)',
                            position: 'relative',
                          }}
                        >
                          {word}
                        </motion.span>
                      </AnimatePresence>
                      <span
                        aria-hidden
                        style={{
                          display: 'block',
                          height: 1,
                          marginTop: 5,
                          width: '100%',
                          background: 'var(--red)',
                          transformOrigin: 'left',
                          opacity: 0.92,
                        }}
                      />
                    </span>
                    <span
                      aria-hidden
                      style={{
                        width: '0.14em',
                        height: '0.14em',
                        minWidth: 5,
                        minHeight: 5,
                        maxWidth: 9,
                        maxHeight: 9,
                        borderRadius: '50%',
                        background: 'var(--ink-tertiary)',
                        opacity: 0.78,
                        marginBottom: '0.24em',
                        flexShrink: 0,
                      }}
                    />
                  </motion.span>
                </h1>
              </div>
            </div>
          </div>

          <div aria-hidden style={{ flex: '0 0 clamp(10px, 2.5vh, 32px)', minHeight: 0 }} />
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
