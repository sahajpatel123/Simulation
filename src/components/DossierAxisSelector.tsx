'use client'

import { Box, Cpu, LucideIcon } from 'lucide-react'

export type DossierAxis = 'software' | 'hardware'

type Opt = {
  value: DossierAxis
  label: string
  kicker: string
  line: string
  icon: LucideIcon
  accent: string
  rail: string
}

const options: Opt[] = [
  {
    value: 'software',
    label: 'Software & service',
    kicker: 'Plate A — digital',
    line: 'Screens, flows, and the argument you ship as bits. Prototype the interface; the press reads it as a product story.',
    icon: Cpu,
    accent: 'var(--red)',
    rail: 'var(--ink)',
  },
  {
    value: 'hardware',
    label: 'Hardware & matter',
    kicker: 'Plate B — physical',
    line: 'Geometry, load, and the thing that exists in a hand. The atelier folio; stress paths and part zones only.',
    icon: Box,
    accent: 'var(--workshop)',
    rail: 'var(--workshop)',
  },
]

type Props = {
  value: DossierAxis
  onChange: (v: DossierAxis) => void
}

/**
 * Choose whether a new dossier follows the software (UI / prototype) path
 * or the hardware workshop path. Legacy dossiers with no value still see both.
 */
export function DossierAxisSelector({ value, onChange }: Props) {
  return (
    <div style={{ marginBottom: 20 }}>
      <div
        className="kicker"
        style={{
          color: 'var(--ink-secondary)',
          marginBottom: 10,
          display: 'flex',
          alignItems: 'center',
          gap: 8,
        }}
      >
        <span style={{ width: 16, height: 0.5, background: 'var(--ink-tertiary)' }} />
        What are we proving?
        <span style={{ fontSize: 9, letterSpacing: '0.2em', color: 'var(--ink-tertiary)' }}>(one path)</span>
      </div>
      <div
        style={{
          display: 'grid',
          gridTemplateColumns: '1fr 1fr',
          gap: 10,
        }}
      >
        {options.map((o) => {
          const active = value === o.value
          const Icon = o.icon
          return (
            <button
              key={o.value}
              type="button"
              onClick={() => onChange(o.value)}
              style={{
                textAlign: 'left',
                padding: '14px 14px 16px',
                border: `0.5px solid ${active ? o.rail : 'var(--border-strong)'}`,
                borderLeft: active ? `4px solid ${o.rail}` : '0.5px solid var(--border-strong)',
                background: active
                  ? 'linear-gradient(135deg, rgba(26,23,20,0.04) 0%, var(--paper) 100%)'
                  : 'rgba(26,23,20,0.02)',
                cursor: 'pointer',
                transition: 'border-color 180ms ease, box-shadow 180ms ease, transform 180ms ease',
                boxShadow: active ? '6px 6px 0 rgba(26,23,20,0.08)' : 'none',
              }}
            >
              <div
                style={{
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'space-between',
                  gap: 8,
                  marginBottom: 6,
                }}
              >
                <span
                  style={{
                    fontSize: 9,
                    letterSpacing: '0.22em',
                    textTransform: 'uppercase',
                    color: o.accent,
                    fontWeight: 600,
                  }}
                >
                  {o.kicker}
                </span>
                <Icon style={{ width: 16, height: 16, color: o.accent, opacity: active ? 1 : 0.5 }} />
              </div>
              <div
                className="font-serif"
                style={{
                  fontSize: 16,
                  fontWeight: 800,
                  fontStyle: 'italic',
                  lineHeight: 1.15,
                  color: 'var(--ink)',
                  marginBottom: 6,
                }}
              >
                {o.label}
              </div>
              <p style={{ fontSize: 12, lineHeight: 1.5, color: 'var(--ink-secondary)', fontWeight: 300 }}>
                {o.line}
              </p>
            </button>
          )
        })}
      </div>
      <p
        style={{
          marginTop: 10,
          fontSize: 10.5,
          lineHeight: 1.5,
          color: 'var(--ink-tertiary)',
          fontStyle: 'italic',
        }}
      >
        This locks the folio: software dossiers don&rsquo;t show the hardware atelier, and hardware dossiers don&rsquo;t
        show the software plate. Older entries in your archive may still list both.
      </p>
    </div>
  )
}
