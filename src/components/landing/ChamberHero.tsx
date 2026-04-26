'use client'

import { useEffect, useRef, useState } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import { ArrowRight, ArrowDown } from 'lucide-react'
import InkBurst, { type InkBurstHandle } from './InkBurst'

const LINES = [
  'Every idea is a hypothesis.',
  'Some survive. Most do not.',
  'You are about to find out which yours is.',
]

const FAST = 28 // ms per char
const PAUSE = 700

/**
 * Black "press chamber" hero. Cursor blinks, then a thesis is typewritten
 * line by line. After it lands, a single CTA prints itself in. Pressing
 * the CTA detonates an ink burst over the entire viewport, which then
 * drains away to reveal the rest of the page.
 */
export default function ChamberHero({
  onEnter,
  onSignIn,
}: {
  /** Fired after the ink burst peaks — parent should scroll-down or open auth. */
  onEnter: () => void
  onSignIn: () => void
}) {
  const [lineIdx, setLineIdx] = useState(0)
  const [typed, setTyped] = useState<string[]>(['', '', ''])
  const [done, setDone] = useState(false)
  const [bursting, setBursting] = useState(false)
  const burstRef = useRef<InkBurstHandle>(null)
  const ctaRef = useRef<HTMLButtonElement>(null)

  // Typewriter sequence
  useEffect(() => {
    if (lineIdx >= LINES.length) {
      const t = setTimeout(() => setDone(true), 500)
      return () => clearTimeout(t)
    }
    const target = LINES[lineIdx]
    let i = 0
    const id = setInterval(() => {
      i++
      setTyped(prev => {
        const next = [...prev]
        next[lineIdx] = target.slice(0, i)
        return next
      })
      if (i >= target.length) {
        clearInterval(id)
        setTimeout(() => setLineIdx(n => n + 1), PAUSE)
      }
    }, FAST)
    return () => clearInterval(id)
  }, [lineIdx])

  const triggerBurst = () => {
    if (bursting) return
    setBursting(true)
    const rect = ctaRef.current?.getBoundingClientRect()
    const x = rect ? rect.left + rect.width / 2 : window.innerWidth / 2
    const y = rect ? rect.top + rect.height / 2 : window.innerHeight / 2
    burstRef.current?.burst(x, y, () => {
      onEnter()
      setTimeout(() => setBursting(false), 1400)
    })
  }

  return (
    <section
      style={{
        position: 'relative',
        height: '100vh',
        background: '#0c0a08',
        color: 'var(--paper)',
        overflow: 'hidden',
      }}
    >
      {/* Subtle noise / film-grain wash */}
      <div
        aria-hidden
        style={{
          position: 'absolute',
          inset: 0,
          opacity: 0.35,
          backgroundImage:
            'radial-gradient(rgba(242,236,224,0.04) 1px, transparent 1px), radial-gradient(rgba(192,57,43,0.05) 1px, transparent 1px)',
          backgroundSize: '4px 4px, 9px 9px',
          backgroundPosition: '0 0, 1px 2px',
          mixBlendMode: 'screen',
          pointerEvents: 'none',
        }}
      />

      {/* Top tier strip */}
      <header
        style={{
          position: 'absolute',
          top: 0,
          left: 0,
          right: 0,
          padding: '20px 36px',
          display: 'grid',
          gridTemplateColumns: '1fr auto 1fr',
          alignItems: 'center',
          fontSize: 10,
          letterSpacing: '0.22em',
          textTransform: 'uppercase',
          color: 'rgba(242,236,224,0.4)',
          borderBottom: '0.5px solid rgba(242,236,224,0.08)',
          zIndex: 5,
        }}
      >
        <span style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
          <span
            style={{
              width: 6,
              height: 6,
              borderRadius: '50%',
              background: 'var(--red)',
              animation: 'pulse-red 1.6s ease-in-out infinite',
            }}
          />
          The Press Is Open
        </span>
        <span
          className="font-serif"
          style={{
            fontSize: 18,
            fontWeight: 900,
            fontStyle: 'italic',
            color: 'var(--paper)',
            letterSpacing: '-0.03em',
          }}
        >
          TheCee
        </span>
        <button
          type="button"
          onClick={onSignIn}
          style={{
            justifySelf: 'end',
            background: 'none',
            border: 'none',
            cursor: 'pointer',
            font: 'inherit',
            fontSize: 10,
            letterSpacing: '0.22em',
            textTransform: 'uppercase',
            color: 'rgba(242,236,224,0.7)',
            display: 'inline-flex',
            alignItems: 'center',
            gap: 8,
          }}
          onMouseEnter={e => (e.currentTarget.style.color = 'var(--red)')}
          onMouseLeave={e => (e.currentTarget.style.color = 'rgba(242,236,224,0.7)')}
        >
          Press pass <ArrowRight size={11} />
        </button>
      </header>

      {/* Big sigil — single italicised "C" pressed in the corner */}
      <div
        aria-hidden
        className="font-serif"
        style={{
          position: 'absolute',
          right: -40,
          bottom: -120,
          fontSize: 480,
          fontWeight: 900,
          fontStyle: 'italic',
          lineHeight: 1,
          color: 'rgba(242,236,224,0.025)',
          userSelect: 'none',
          pointerEvents: 'none',
        }}
      >
        C
      </div>

      {/* Centre — typewriter thesis */}
      <div
        style={{
          position: 'absolute',
          inset: 0,
          display: 'flex',
          flexDirection: 'column',
          alignItems: 'center',
          justifyContent: 'center',
          padding: '0 32px',
          textAlign: 'center',
        }}
      >
        <div style={{ maxWidth: 1100 }}>
          <div
            style={{
              fontSize: 10,
              letterSpacing: '0.32em',
              textTransform: 'uppercase',
              color: 'var(--red)',
              fontWeight: 600,
              marginBottom: 28,
              display: 'inline-flex',
              alignItems: 'center',
              gap: 12,
            }}
          >
            <span style={{ height: 1, width: 28, background: 'var(--red)' }} />
            Thesis · No. 0001
            <span style={{ height: 1, width: 28, background: 'var(--red)' }} />
          </div>

          {LINES.map((target, i) => {
            const visible = typed[i]
            const isCurrent = i === lineIdx && !done
            const isBlank = !visible && i > lineIdx
            if (isBlank) return null
            return (
              <div
                key={i}
                className="font-serif"
                style={{
                  fontSize: i === LINES.length - 1
                    ? 'clamp(28px, 3.4vw, 52px)'
                    : 'clamp(38px, 5vw, 76px)',
                  fontWeight: i === LINES.length - 1 ? 400 : 800,
                  fontStyle: i === LINES.length - 1 ? 'italic' : 'normal',
                  color: i === LINES.length - 1 ? 'rgba(242,236,224,0.55)' : 'var(--paper)',
                  letterSpacing: '-0.03em',
                  lineHeight: 1.1,
                  marginBottom: 14,
                }}
              >
                {visible}
                {isCurrent && <Caret />}
              </div>
            )
          })}

          {/* CTA fades in once typing completes */}
          <AnimatePresence>
            {done && (
              <motion.div
                initial={{ opacity: 0, y: 18 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ duration: 0.7, ease: [0.2, 0.7, 0.2, 1] }}
                style={{
                  marginTop: 56,
                  display: 'flex',
                  flexDirection: 'column',
                  alignItems: 'center',
                  gap: 22,
                }}
              >
                <button
                  ref={ctaRef}
                  type="button"
                  onClick={triggerBurst}
                  disabled={bursting}
                  style={{
                    background: 'var(--red)',
                    color: 'var(--paper)',
                    border: 'none',
                    padding: '18px 42px',
                    fontSize: 12,
                    letterSpacing: '0.3em',
                    textTransform: 'uppercase',
                    fontWeight: 700,
                    cursor: bursting ? 'wait' : 'pointer',
                    fontFamily: 'inherit',
                    display: 'inline-flex',
                    alignItems: 'center',
                    gap: 14,
                    position: 'relative',
                    boxShadow: '0 0 0 0.5px rgba(242,236,224,0.2), 12px 12px 0 rgba(192,57,43,0.18)',
                    transition: 'transform 200ms ease, box-shadow 200ms ease',
                  }}
                  onMouseEnter={e => {
                    if (!bursting) {
                      e.currentTarget.style.transform = 'translate(-2px,-2px)'
                      e.currentTarget.style.boxShadow =
                        '0 0 0 0.5px rgba(242,236,224,0.2), 16px 16px 0 rgba(192,57,43,0.28)'
                    }
                  }}
                  onMouseLeave={e => {
                    e.currentTarget.style.transform = 'translate(0,0)'
                    e.currentTarget.style.boxShadow =
                      '0 0 0 0.5px rgba(242,236,224,0.2), 12px 12px 0 rgba(192,57,43,0.18)'
                  }}
                >
                  Run the press <ArrowRight size={14} />
                </button>

                <button
                  type="button"
                  onClick={onEnter}
                  style={{
                    background: 'none',
                    border: 'none',
                    cursor: 'pointer',
                    color: 'rgba(242,236,224,0.5)',
                    fontSize: 10,
                    letterSpacing: '0.32em',
                    textTransform: 'uppercase',
                    fontFamily: 'inherit',
                    display: 'inline-flex',
                    alignItems: 'center',
                    gap: 10,
                  }}
                  onMouseEnter={e => (e.currentTarget.style.color = 'var(--paper)')}
                  onMouseLeave={e => (e.currentTarget.style.color = 'rgba(242,236,224,0.5)')}
                >
                  or read the issue first <ArrowDown size={11} />
                </button>
              </motion.div>
            )}
          </AnimatePresence>
        </div>
      </div>

      {/* Footer strip */}
      <footer
        style={{
          position: 'absolute',
          bottom: 0,
          left: 0,
          right: 0,
          padding: '18px 36px',
          display: 'grid',
          gridTemplateColumns: '1fr 1fr 1fr',
          fontSize: 10,
          letterSpacing: '0.22em',
          textTransform: 'uppercase',
          color: 'rgba(242,236,224,0.32)',
          borderTop: '0.5px solid rgba(242,236,224,0.08)',
          zIndex: 5,
        }}
      >
        <span>Vol. I — Issue 04</span>
        <span style={{ textAlign: 'center' }}>The simulation broadsheet</span>
        <span style={{ textAlign: 'right' }}>Est. 2026</span>
      </footer>

      <InkBurst ref={burstRef} />
    </section>
  )
}

function Caret() {
  return (
    <span
      style={{
        display: 'inline-block',
        width: '0.55ch',
        background: 'var(--red)',
        height: '1em',
        marginLeft: 6,
        verticalAlign: '-0.12em',
        animation: 'caret-blink 0.9s steps(2) infinite',
      }}
    />
  )
}
