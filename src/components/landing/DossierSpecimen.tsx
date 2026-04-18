'use client'

import { motion, useInView } from 'framer-motion'
import { useRef } from 'react'
import { ArrowUpRight } from 'lucide-react'

const ROWS = [
  { n: '01', title: 'Rural D2C cold-press', kicker: 'Pricing · Channel', status: 'done', stamp: 'Filed' },
  { n: '02', title: 'B2B contract intel', kicker: 'GTM · Positioning', status: 'running', stamp: 'At press' },
  { n: '03', title: 'Tier-2 fintech onboarding', kicker: 'Activation · Risk', status: 'ready', stamp: 'Proof set' },
  { n: '04', title: 'Indie game launch window', kicker: 'Demand · Timing', status: 'draft', stamp: 'In notes' },
] as const

const dotColor: Record<string, string> = {
  draft: 'var(--ink-tertiary)',
  ready: '#b88a3a',
  running: 'var(--red)',
  done: '#3d7a4a',
}

/**
 * A specimen of the dossier index — the same row anatomy you see inside
 * the workspace, but here it animates row-by-row as the page reveals,
 * as if the press is stamping freshly typeset entries into the ledger.
 */
export default function DossierSpecimen() {
  const ref = useRef<HTMLDivElement>(null)
  const inView = useInView(ref, { once: true, margin: '-80px' })

  return (
    <div ref={ref}>
      {ROWS.map((r, i) => (
        <motion.div
          key={r.n}
          initial={{ opacity: 0, y: 18 }}
          animate={inView ? { opacity: 1, y: 0 } : {}}
          transition={{ duration: 0.7, delay: i * 0.12, ease: [0.2, 0.7, 0.2, 1] }}
          style={{
            position: 'relative',
            display: 'grid',
            gridTemplateColumns: '88px minmax(0,1fr) 160px 120px 24px',
            alignItems: 'center',
            gap: 28,
            padding: '28px 0 26px',
            borderTop: '0.5px solid var(--border-color)',
            cursor: 'default',
          }}
        >
          <span
            className="font-serif numeral"
            style={{ fontSize: 32, color: 'var(--ink-tertiary)', letterSpacing: '-0.02em' }}
          >
            {r.n}
          </span>

          <div>
            <div
              className="font-serif"
              style={{
                fontSize: 22,
                fontWeight: 800,
                color: 'var(--ink)',
                letterSpacing: '-0.01em',
                lineHeight: 1.15,
                fontStyle: 'italic',
              }}
            >
              {r.title}
            </div>
            <div
              style={{
                marginTop: 6,
                fontSize: 10,
                letterSpacing: '0.18em',
                textTransform: 'uppercase',
                color: 'var(--ink-secondary)',
              }}
            >
              {r.kicker}
            </div>
          </div>

          <div
            style={{
              fontSize: 10,
              letterSpacing: '0.18em',
              textTransform: 'uppercase',
              color: 'var(--ink-secondary)',
              display: 'flex',
              alignItems: 'center',
              gap: 8,
            }}
          >
            <span
              style={{
                width: 6,
                height: 6,
                borderRadius: '50%',
                background: dotColor[r.status],
                display: 'inline-block',
                animation: r.status === 'running' ? 'pulse-red 1.6s ease-in-out infinite' : undefined,
              }}
            />
            {r.stamp}
          </div>

          {/* Inked-on stamp on the right — rotated paper stamp */}
          <motion.div
            initial={{ opacity: 0, rotate: -10, scale: 0.85 }}
            animate={inView ? { opacity: 1, rotate: -6, scale: 1 } : {}}
            transition={{ duration: 0.6, delay: 0.25 + i * 0.12 }}
            style={{
              border: '1.2px solid var(--red)',
              padding: '4px 10px',
              fontSize: 9,
              letterSpacing: '0.22em',
              textTransform: 'uppercase',
              color: 'var(--red)',
              fontWeight: 700,
              transformOrigin: 'center',
              justifySelf: 'end',
              whiteSpace: 'nowrap',
            }}
          >
            Vol. I · {r.n}
          </motion.div>

          <ArrowUpRight size={14} style={{ color: 'var(--ink-tertiary)' }} />
        </motion.div>
      ))}
    </div>
  )
}
