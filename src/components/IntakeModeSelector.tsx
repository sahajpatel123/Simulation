'use client'

import { motion } from 'framer-motion'

export type IntakeMode = 'IDEA' | 'MID_BUILD' | 'PRE_LAUNCH'

interface IntakeModeSelectorProps {
  value: IntakeMode
  onChange: (mode: IntakeMode) => void
}

const MODES: {
  key: IntakeMode
  label: string
  description: string
  icon: string
  hint: string
}[] = [
  {
    key: 'IDEA',
    label: 'I have an idea',
    description: 'You are describing a product you have not built yet.',
    icon: '💡',
    hint: 'Assumptions treated as design intent',
  },
  {
    key: 'MID_BUILD',
    label: "I'm mid-build",
    description: 'You have shipped features and know what you are building.',
    icon: '🔨',
    hint: 'Assumptions treated as internally validated',
  },
  {
    key: 'PRE_LAUNCH',
    label: "I'm pre-launch",
    description: 'Product is ready. You are about to launch or have launched.',
    icon: '🚀',
    hint: 'Pricing claims treated as externally validated',
  },
]

export function IntakeModeSelector({ value, onChange }: IntakeModeSelectorProps) {
  return (
    <div style={{ marginBottom: 16 }}>
      <p
        className="kicker"
        style={{
          fontSize: 10,
          letterSpacing: '0.2em',
          textTransform: 'uppercase',
          color: 'var(--ink-tertiary)',
          marginBottom: 10,
        }}
      >
        Where are you in the build?
      </p>
      <div
        style={{
          display: 'grid',
          gridTemplateColumns: 'repeat(3, minmax(0, 1fr))',
          gap: 10,
        }}
      >
        {MODES.map((mode) => {
          const selected = value === mode.key
          return (
            <motion.button
              key={mode.key}
              type="button"
              onClick={() => onChange(mode.key)}
              whileHover={{ scale: 1.01 }}
              whileTap={{ scale: 0.99 }}
              style={{
                position: 'relative',
                padding: 14,
                borderRadius: 0,
                border: '0.5px solid ' + (selected ? 'var(--ink)' : 'var(--border-strong)'),
                background: selected ? 'rgba(26, 23, 20, 0.06)' : 'rgba(26, 23, 20, 0.02)',
                textAlign: 'left' as const,
                cursor: 'pointer',
                transition: 'border 180ms ease, background 180ms ease',
              }}
            >
              {selected && (
                <div
                  style={{
                    position: 'absolute',
                    top: 10,
                    right: 10,
                    width: 6,
                    height: 6,
                    background: 'var(--red)',
                  }}
                />
              )}
              <div style={{ fontSize: 22, marginBottom: 6 }}>{mode.icon}</div>
              <p
                style={{
                  fontSize: 12,
                  fontWeight: 800,
                  marginBottom: 4,
                  color: 'var(--ink)',
                  lineHeight: 1.2,
                }}
              >
                {mode.label}
              </p>
              <p
                style={{
                  fontSize: 11,
                  lineHeight: 1.5,
                  color: 'var(--ink-secondary)',
                  fontWeight: 300,
                }}
              >
                {mode.description}
              </p>
              <p
                className="kicker"
                style={{
                  marginTop: 8,
                  fontSize: 9,
                  color: selected ? 'var(--red)' : 'var(--ink-tertiary)',
                  lineHeight: 1.3,
                }}
              >
                {mode.hint}
              </p>
            </motion.button>
          )
        })}
      </div>
    </div>
  )
}
