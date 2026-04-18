'use client'

import { useEffect, useRef, useState } from 'react'

/**
 * Three live press metrics. Numbers are seeded with deterministic
 * starting values then tick upward at staggered cadences, like a press
 * counter on the wall of the print shop.
 */
type Seed = {
  kicker: string
  label: string
  base: number
  cadenceMs: number
  increment: () => number
  suffix: string
  floor: number
}

const SEEDS: Seed[] = [
  {
    kicker: 'Press · Live',
    label: 'Scenarios at press',
    base: 1_420_812,
    cadenceMs: 220,
    increment: () => 1 + Math.floor(Math.random() * 7),
    suffix: '',
    floor: 0,
  },
  {
    kicker: 'Today · Filed',
    label: 'Dossiers archived',
    base: 87,
    cadenceMs: 4400,
    increment: () => 1,
    suffix: '',
    floor: 0,
  },
  {
    kicker: 'In type · Now',
    label: 'Founders writing',
    base: 12,
    cadenceMs: 6000,
    increment: () => (Math.random() > 0.5 ? 1 : -1),
    suffix: '',
    floor: 4,
  },
]

export default function LiveCounters() {
  return (
    <div
      style={{
        border: '0.5px solid var(--ink)',
        background: 'var(--paper)',
        display: 'grid',
        gridTemplateRows: '1fr 1fr 1fr',
      }}
    >
      {SEEDS.map((s, i) => (
        <Counter key={s.label} seed={s} divider={i < SEEDS.length - 1} />
      ))}
    </div>
  )
}

function Counter({
  seed,
  divider,
}: {
  seed: Seed
  divider: boolean
}) {
  const [n, setN] = useState(seed.base)
  const ref = useRef(seed.base)

  useEffect(() => {
    const id = setInterval(() => {
      const delta = seed.increment()
      ref.current = Math.max(seed.floor, ref.current + delta)
      setN(ref.current)
    }, seed.cadenceMs)
    return () => clearInterval(id)
  }, [seed])

  return (
    <div
      style={{
        padding: '20px 22px',
        borderBottom: divider ? '0.5px solid var(--border-color)' : 'none',
        display: 'flex',
        flexDirection: 'column',
        justifyContent: 'space-between',
        minHeight: 110,
        position: 'relative',
      }}
    >
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          gap: 8,
          fontSize: 9,
          letterSpacing: '0.22em',
          textTransform: 'uppercase',
          color: 'var(--red)',
          fontWeight: 600,
        }}
      >
        <span
          style={{
            width: 6,
            height: 6,
            borderRadius: '50%',
            background: 'var(--red)',
            display: 'inline-block',
            animation: 'pulse-red 1.6s ease-in-out infinite',
          }}
        />
        {seed.kicker}
      </div>
      <div
        className="numeral font-serif"
        style={{
          fontSize: 'clamp(34px, 3vw, 44px)',
          color: 'var(--ink)',
          fontVariantNumeric: 'lining-nums tabular-nums',
        }}
      >
        {n.toLocaleString()}
        {seed.suffix}
      </div>
      <div
        style={{
          fontSize: 10,
          letterSpacing: '0.14em',
          textTransform: 'uppercase',
          color: 'var(--ink-secondary)',
        }}
      >
        {seed.label}
      </div>
    </div>
  )
}
