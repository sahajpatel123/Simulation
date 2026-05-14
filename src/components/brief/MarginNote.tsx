'use client'

import { useMemo } from 'react'

interface MarginNoteProps {
  mode: 'refine' | 'suggest' | 'critique'
  result: string | string[]
  onClose: () => void
  onApply: (value: string) => void
}

function noteRotation(seed: string) {
  let h = 0
  for (let i = 0; i < seed.length; i++) {
    h = (h * 31 + seed.charCodeAt(i)) | 0
  }
  return ((h % 280) / 100) - 1.4
}

export default function MarginNote({ mode, result, onClose, onApply }: MarginNoteProps) {
  const seedStr = mode + (Array.isArray(result) ? result.join('') : result).slice(0, 30)
  const rotation = useMemo(() => noteRotation(seedStr), [seedStr])

  const modeMeta = {
    refine: { label: 'A REFINED LINE', verb: 'the editor offers' },
    suggest: { label: 'THREE ANGLES', verb: 'the editor proposes' },
    critique: { label: "THE EDITOR'S MARK", verb: 'the editor notes' },
  }
  const meta = modeMeta[mode]

  return (
    <div
      style={{
        position: 'relative',
        animation: 'noteSlide 420ms cubic-bezier(0.16, 1, 0.3, 1)',
        transform: `rotate(${rotation}deg)`,
        transformOrigin: 'top left',
      }}
    >
      {/* Brass pin */}
      <div
        style={{
          position: 'absolute',
          top: -6, left: 18,
          width: 11, height: 11,
          borderRadius: '50%',
          background: 'radial-gradient(circle at 35% 30%, #d4af6a 0%, #a8843c 60%, #6b5024 100%)',
          boxShadow: '0 1px 2px rgba(0,0,0,0.4), inset -1px -1px 1px rgba(0,0,0,0.3)',
          zIndex: 5,
        }}
      />

      {/* Paper slip */}
      <div
        style={{
          position: 'relative',
          background: '#fdf8ed',
          padding: '20px 18px 16px 18px',
          maxWidth: 280,
          boxShadow: '0 1px 1px rgba(0,0,0,0.04), 0 12px 28px rgba(0,0,0,0.10), 0 22px 48px rgba(0,0,0,0.06)',
          clipPath:
            'polygon(' +
            '0% 0%, 100% 0%, 100% 96%, ' +
            '97% 100%, 88% 97%, 74% 99%, 60% 96%, 44% 99%, 28% 97%, 14% 99%, 4% 97%, 0% 100%' +
            ')',
          backgroundImage:
            'repeating-linear-gradient(0deg, ' +
            'rgba(180,140,90,0.02) 0px, rgba(180,140,90,0.02) 1px, transparent 1px, transparent 3px' +
            ')',
        }}
      >
        {/* Header */}
        <div
          style={{
            display: 'flex', justifyContent: 'space-between', alignItems: 'baseline',
            marginBottom: 4, paddingBottom: 8, borderBottom: '0.5px dashed #c0392b66',
          }}
        >
          <span style={{ fontFamily: 'var(--font-mono), monospace', fontSize: 8, letterSpacing: '0.26em', color: '#c0392b', fontWeight: 600 }}>
            {meta.label}
          </span>
          <button onClick={onClose} style={{ background: 'transparent', border: 'none', cursor: 'pointer', color: '#999', fontSize: 16, lineHeight: 1, padding: 0, fontFamily: 'var(--font-serif), serif' }} aria-label="Dismiss">✕</button>
        </div>

        <div style={{ fontFamily: 'var(--font-serif), serif', fontStyle: 'italic', fontSize: 11, color: '#888', marginBottom: 12 }}>— {meta.verb} —</div>

        {/* Content */}
        {Array.isArray(result) ? (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
            {result.map((opt, i) => (
              <div key={i} style={{ paddingBottom: 12, borderBottom: i < result.length - 1 ? '0.5px solid rgba(192,57,43,0.18)' : 'none' }}>
                <div style={{ display: 'flex', gap: 8, alignItems: 'baseline', marginBottom: 8 }}>
                  <span style={{ fontFamily: 'var(--font-mono), monospace', fontSize: 9, color: '#c0392b', letterSpacing: '0.15em', flexShrink: 0 }}>
                    №{String(i + 1).padStart(2, '0')}
                  </span>
                  <div style={{ fontFamily: 'var(--font-serif), serif', fontSize: 14, color: '#1a1a1a', lineHeight: 1.45, flex: 1 }}>{opt}</div>
                </div>
                <button
                  onClick={() => onApply(opt)}
                  style={{
                    background: 'transparent', border: 'none', padding: 0, paddingLeft: 22,
                    fontFamily: 'var(--font-serif), serif', fontStyle: 'italic', fontSize: 12,
                    cursor: 'pointer', color: '#c0392b',
                    textDecoration: 'underline', textDecorationStyle: 'wavy',
                    textDecorationThickness: '0.5px', textUnderlineOffset: '3px',
                  }}
                >
                  ink this in
                </button>
              </div>
            ))}
          </div>
        ) : mode === 'refine' ? (
          <div>
            <div style={{ fontFamily: 'var(--font-serif), serif', fontSize: 15, color: '#1a1a1a', lineHeight: 1.5, marginBottom: 14, fontStyle: 'italic' }}>"{result}"</div>
            <button
              onClick={() => onApply(result)}
              style={{
                background: '#c0392b', color: '#fdf8ed', border: 'none',
                padding: '6px 14px', fontFamily: 'var(--font-mono), monospace',
                fontSize: 9, letterSpacing: '0.20em', cursor: 'pointer', fontWeight: 600,
              }}
            >
              INK THIS IN
            </button>
          </div>
        ) : (
          <div style={{ fontFamily: 'var(--font-serif), serif', fontSize: 13, color: '#1a1a1a', lineHeight: 1.55, whiteSpace: 'pre-wrap', fontStyle: 'italic' }}>{result}</div>
        )}

        {/* Footer */}
        <div style={{ marginTop: 14, paddingTop: 8, borderTop: '0.5px dashed rgba(0,0,0,0.10)', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
          <span style={{ fontFamily: 'var(--font-mono), monospace', fontSize: 7, letterSpacing: '0.30em', color: '#aaa' }}>THE EDITOR'S DESK</span>
          <span style={{ fontFamily: 'var(--font-mono), monospace', fontSize: 7, letterSpacing: '0.20em', color: '#aaa' }}>✓ ed.</span>
        </div>
      </div>

      <style>{`
        @keyframes noteSlide {
          0% { opacity: 0; transform: translateX(40px) translateY(-12px) rotate(${rotation - 4}deg) scale(0.92); }
          60% { opacity: 1; transform: translateX(-4px) translateY(2px) rotate(${rotation + 0.5}deg) scale(1.01); }
          100% { opacity: 1; transform: translateX(0) translateY(0) rotate(${rotation}deg) scale(1); }
        }
      `}</style>
    </div>
  )
}
