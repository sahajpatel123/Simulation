'use client'

import { useRef } from 'react'
import { motion, useScroll, useTransform, type MotionValue } from 'framer-motion'

type Plate = {
  n: string
  kicker: string
  title: string
  body: string
}

/**
 * Sticky, scroll-driven plate advance. Three plates travel horizontally
 * across the viewport as the user scrolls the section, with a typeset
 * progress ledger underneath.
 */
export default function ProcessReel({ plates }: { plates: readonly Plate[] }) {
  const ref = useRef<HTMLDivElement>(null)
  const { scrollYProgress } = useScroll({
    target: ref,
    offset: ['start start', 'end end'],
  })

  const x = useTransform(scrollYProgress, [0, 1], ['0%', `-${(plates.length - 1) * 100}%`])

  return (
    <section
      id="how"
      style={{
        borderBottom: '0.5px solid var(--border-color)',
        background: 'var(--paper)',
        position: 'relative',
      }}
    >
      {/* Heading rail */}
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

      {/* Scroll track — 3× viewport tall so each plate gets real scroll */}
      <div ref={ref} style={{ height: `${plates.length * 100}vh`, position: 'relative' }}>
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
          <motion.div
            style={{
              display: 'flex',
              width: `${plates.length * 100}%`,
              x,
            }}
          >
            {plates.map((p, i) => (
              <Plate key={p.n} plate={p} index={i} progress={scrollYProgress} total={plates.length} />
            ))}
          </motion.div>

          {/* Ledger of progress */}
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
            <Ledger plates={plates} progress={scrollYProgress} />
          </div>
        </div>
      </div>
    </section>
  )
}

function Plate({
  plate,
  index,
  progress,
  total,
}: {
  plate: Plate
  index: number
  progress: MotionValue<number>
  total: number
}) {
  const center = index / (total - 1)
  const span = 1 / (total - 1)

  // A subtle lift + shadow as this plate passes centre-stage.
  const y = useTransform(progress, [center - span * 0.6, center, center + span * 0.6], [40, 0, -40])
  const opacity = useTransform(
    progress,
    [center - span * 0.7, center, center + span * 0.7],
    [0.3, 1, 0.3]
  )

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
      <motion.article
        style={{
          y,
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
        }}
      >
        {/* torn-paper red edge */}
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
      </motion.article>
    </div>
  )
}

function Ledger({
  plates,
  progress,
}: {
  plates: readonly Plate[]
  progress: MotionValue<number>
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
  progress: MotionValue<number>
}) {
  const center = index / (total - 1)
  const span = 1 / (total - 1)
  const active = useTransform(
    progress,
    [center - span * 0.5, center, center + span * 0.5],
    [0, 1, 0]
  )
  const opacity = useTransform(active, (v) => 0.35 + v * 0.65)
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
      <motion.span
        style={{
          display: 'inline-block',
          width: 8,
          height: 8,
          borderRadius: '50%',
          background: 'var(--red)',
          scale: active,
        }}
      />
      <motion.span
        style={{
          fontSize: 10,
          letterSpacing: '0.24em',
          textTransform: 'uppercase',
          color: 'var(--ink-secondary)',
          opacity,
          fontWeight: 600,
          fontVariantNumeric: 'tabular-nums',
        }}
      >
        {String(index + 1).padStart(2, '0')} — {plate.kicker}
      </motion.span>
    </div>
  )
}
