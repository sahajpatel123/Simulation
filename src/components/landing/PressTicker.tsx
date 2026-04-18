'use client'

const ITEMS = [
  '243 founders validated this quarter',
  '1,420,000 scenarios run',
  '3× cross-validation by default',
  'Pre-mortem reports filed in under 2 minutes',
  'Today’s market mood — VOLATILE',
  'Press is open · 24 / 7',
  'New: Decision Studio v0.4',
  'Vol. I — Issue 04',
  '0 advisors flattered this morning',
]

export default function PressTicker() {
  const row = (
    <div style={{ display: 'flex', alignItems: 'center', gap: '56px', flexShrink: 0 }}>
      {ITEMS.map(t => (
        <span
          key={t}
          style={{
            fontSize: '11px',
            letterSpacing: '0.18em',
            textTransform: 'uppercase',
            color: 'var(--paper)',
            fontWeight: 500,
            display: 'inline-flex',
            alignItems: 'center',
            gap: 14,
            whiteSpace: 'nowrap',
          }}
        >
          <span style={{ width: 6, height: 6, background: 'var(--red)', display: 'inline-block' }} />
          {t}
        </span>
      ))}
    </div>
  )

  return (
    <div
      style={{
        background: 'var(--ink)',
        borderTop: '0.5px solid rgba(242,236,224,0.08)',
        borderBottom: '0.5px solid rgba(242,236,224,0.08)',
        padding: '14px 0',
        overflow: 'hidden',
        position: 'relative',
      }}
    >
      <div style={{ display: 'flex', width: 'max-content', gap: 56 }} className="animate-marquee">
        {row}
        {row}
      </div>
    </div>
  )
}
