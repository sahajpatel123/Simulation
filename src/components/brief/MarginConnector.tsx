'use client'

interface MarginConnectorProps {
  visible: boolean
}

export default function MarginConnector({ visible }: MarginConnectorProps) {
  if (!visible) return null

  return (
    <svg width="60" height="80" viewBox="0 0 60 80"
      style={{
        position: 'absolute', top: 20, left: -50,
        pointerEvents: 'none', opacity: 0.55,
        animation: 'connectorDraw 600ms ease 200ms both',
      }}
    >
      <path
        d="M 2 40 Q 18 22, 32 30 T 58 24"
        stroke="#c0392b" strokeWidth="1.3" fill="none"
        strokeLinecap="round" strokeDasharray="120" strokeDashoffset="120"
        style={{ animation: 'drawLine 700ms ease 250ms forwards' }}
      />
      <path
        d="M 55 22 L 58 24 L 55 27"
        stroke="#c0392b" strokeWidth="1.3" fill="none"
        strokeLinecap="round" strokeLinejoin="round"
        opacity="0" style={{ animation: 'fadeIn 200ms ease 800ms forwards' }}
      />
      <style>{`
        @keyframes drawLine { to { stroke-dashoffset: 0; } }
        @keyframes fadeIn { to { opacity: 1; } }
        @keyframes connectorDraw { from { opacity: 0; } to { opacity: 0.55; } }
      `}</style>
    </svg>
  )
}
