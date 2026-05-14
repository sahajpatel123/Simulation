'use client'

interface MarginNoteProps {
  mode: 'refine' | 'suggest' | 'critique'
  result: string | string[]
  onClose: () => void
  onApply: (value: string) => void
}

export default function MarginNote({ mode, result, onClose, onApply }: MarginNoteProps) {
  const modeLabels = { refine: 'a refined version', suggest: 'three options', critique: "the editor's critique" }

  return (
    <div
      style={{
        position: 'relative',
        background: '#fffaf2',
        border: '0.5px solid #c0392b',
        borderLeft: '3px solid #c0392b',
        padding: '14px 16px',
        maxWidth: 280,
        animation: 'noteAppear 360ms ease',
        transform: 'rotate(-0.3deg)',
        boxShadow: '0 8px 24px rgba(0,0,0,0.06)',
      }}
    >
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 10 }}>
        <span style={{ fontFamily: 'var(--font-mono), monospace', fontSize: 8, letterSpacing: '0.24em', color: '#c0392b' }}>
          MARGIN NOTE
        </span>
        <button onClick={onClose} style={{ background: 'transparent', border: 'none', cursor: 'pointer', color: '#888', fontSize: 14, lineHeight: 1, padding: 0 }}>
          ×
        </button>
      </div>

      <div style={{ fontFamily: 'var(--font-serif), serif', fontStyle: 'italic', fontSize: 11, color: '#888', marginBottom: 10 }}>
        The editor offers {modeLabels[mode]}:
      </div>

      {Array.isArray(result) ? (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
          {result.map((opt, i) => (
            <div
              key={i}
              style={{
                paddingBottom: 10,
                borderBottom: i < result.length - 1 ? '0.5px solid rgba(192,57,43,0.18)' : 'none',
              }}
            >
              <div style={{ fontFamily: 'var(--font-serif), serif', fontSize: 14, color: '#1a1a1a', lineHeight: 1.45, marginBottom: 6 }}>
                {opt}
              </div>
              <button
                onClick={() => onApply(opt)}
                style={{
                  background: 'transparent',
                  border: '0.5px solid #1a1a1a',
                  padding: '4px 10px',
                  fontFamily: 'var(--font-mono), monospace',
                  fontSize: 8,
                  letterSpacing: '0.20em',
                  cursor: 'pointer',
                  color: '#1a1a1a',
                }}
              >
                INK THIS IN
              </button>
            </div>
          ))}
        </div>
      ) : mode === 'refine' ? (
        <div>
          <div style={{ fontFamily: 'var(--font-serif), serif', fontSize: 14, color: '#1a1a1a', lineHeight: 1.45, marginBottom: 10 }}>
            {result}
          </div>
          <button
            onClick={() => onApply(result)}
            style={{
              background: '#c0392b',
              color: '#f5f0e8',
              border: 'none',
              padding: '5px 11px',
              fontFamily: 'var(--font-mono), monospace',
              fontSize: 8,
              letterSpacing: '0.20em',
              cursor: 'pointer',
            }}
          >
            INK THIS IN
          </button>
        </div>
      ) : (
        <div style={{ fontFamily: 'var(--font-serif), serif', fontSize: 13, color: '#1a1a1a', lineHeight: 1.5, whiteSpace: 'pre-wrap' }}>
          {result}
        </div>
      )}

      <style>{`
        @keyframes noteAppear {
          from { opacity: 0; transform: translateX(20px) rotate(-0.3deg); }
          to { opacity: 1; transform: translateX(0) rotate(-0.3deg); }
        }
      `}</style>
    </div>
  )
}
