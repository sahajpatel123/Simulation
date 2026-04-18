import type { Intervention } from '@/types'
import { TrendingUp, Zap, Clock } from 'lucide-react'

const effortConfig = {
  LOW: {
    label: 'Low effort',
    color: '#1a6b55',
    bg: 'rgba(26, 107, 85, 0.08)',
    border: 'rgba(26, 107, 85, 0.25)',
    icon: Zap,
  },
  MEDIUM: {
    label: 'Medium effort',
    color: '#8a5a1a',
    bg: 'rgba(184, 138, 58, 0.12)',
    border: 'rgba(184, 138, 58, 0.35)',
    icon: Clock,
  },
  HIGH: {
    label: 'High effort',
    color: 'var(--red)',
    bg: 'rgba(192, 57, 43, 0.08)',
    border: 'rgba(192, 57, 43, 0.35)',
    icon: TrendingUp,
  },
}

type Effort = keyof typeof effortConfig

export default function InterventionCard({ intervention, rank }: { intervention: Intervention; rank: number }) {
  const raw = intervention.effortLevel ?? intervention.difficulty ?? 'MEDIUM'
  const effortKey = (raw in effortConfig ? raw : 'MEDIUM') as Effort
  const effort = effortConfig[effortKey]
  const EffortIcon = effort.icon

  return (
    <div
      style={{
        border: '0.5px solid var(--border-strong)',
        background: 'var(--paper)',
        padding: 20,
        transition: 'box-shadow 200ms ease, transform 200ms ease',
      }}
      className="rise"
    >
      <div style={{ display: 'flex', alignItems: 'flex-start', gap: 14, marginBottom: 14 }}>
        <div
          style={{
            width: 28,
            height: 28,
            flexShrink: 0,
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            border: '0.5px solid var(--ink)',
            fontFamily: 'var(--font-serif)',
            fontSize: 13,
            fontWeight: 800,
            fontStyle: 'italic',
            color: 'var(--red)',
          }}
        >
          {rank}
        </div>
        <div style={{ flex: 1, minWidth: 0 }}>
          <h4
            style={{
              fontSize: 14,
              fontWeight: 600,
              color: 'var(--ink)',
              marginBottom: 6,
              lineHeight: 1.35,
            }}
          >
            {intervention.title}
          </h4>
          <p style={{ fontSize: 12, lineHeight: 1.6, color: 'var(--ink-secondary)' }}>{intervention.description}</p>
        </div>
      </div>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 12 }}>
        <span
          style={{
            display: 'inline-flex',
            alignItems: 'center',
            gap: 6,
            fontSize: 10,
            letterSpacing: '0.12em',
            textTransform: 'uppercase',
            fontWeight: 600,
            padding: '5px 10px',
            border: `0.5px solid ${effort.border}`,
            color: effort.color,
            background: effort.bg,
          }}
        >
          <EffortIcon style={{ width: 12, height: 12 }} />
          {effort.label}
        </span>
        <span
          style={{
            fontFamily: 'var(--font-serif)',
            fontSize: 15,
            fontWeight: 800,
            fontStyle: 'italic',
            color: 'var(--ink)',
          }}
        >
          +{intervention.probabilityShift}%
        </span>
      </div>
    </div>
  )
}
