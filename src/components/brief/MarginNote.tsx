'use client'

import { useMemo } from 'react'

interface MarginNoteProps {
  mode: 'refine' | 'suggest' | 'critique'
  result: string | string[]
  onClose: () => void
  onApply: (value: string) => void
}

function rotFor(seed: string, range = 2.5) {
  let h = 0
  for (let i = 0; i < seed.length; i++) {
    h = (h * 31 + seed.charCodeAt(i)) | 0
  }
  return ((h % (range * 200)) / 100) - range
}

const RED = '#c0392b'
const RED_SOFT = 'rgba(192,57,43,0.78)'
const PAPER = '#fdf8ed'
const INK = '#1a1a1a'

export default function MarginNote({ mode, result, onClose, onApply }: MarginNoteProps) {
  if (mode === 'suggest' && Array.isArray(result)) {
    return <SuggestSketch options={result} onClose={onClose} onApply={onApply} />
  }

  if (mode === 'refine' && typeof result === 'string') {
    return <SingleTicket label="A REFINED LINE" body={result} showApply onApply={() => onApply(result)} onClose={onClose} />
  }

  return (
    <SingleTicket label="THE EDITOR'S MARK" body={typeof result === 'string' ? result : ''} showApply={false} onApply={() => {}} onClose={onClose} />
  )
}

/* ─── SUGGEST: three tickets on a vertical branch ─────── */

function SuggestSketch({ options, onClose, onApply }: { options: string[]; onClose: () => void; onApply: (v: string) => void }) {
  const TICKET_GAP = 140
  const totalHeight = 60 + options.length * TICKET_GAP

  return (
    <div style={{ position: 'relative', paddingTop: 8, minHeight: totalHeight }}>
      <button onClick={onClose} style={{ position: 'absolute', top: 0, right: 0, background: 'transparent', border: 'none', cursor: 'pointer', color: '#999', fontSize: 18, lineHeight: 1, padding: 4, zIndex: 10 }} aria-label="Dismiss">✕</button>

      <div style={{ fontFamily: 'var(--font-mono), monospace', fontSize: 8, letterSpacing: '0.28em', color: RED, fontWeight: 600, marginBottom: 12, animation: 'fadeSlide 380ms ease both' }}>
        ── THE EDITOR'S SKETCHPAD ──
      </div>
      <div style={{ fontFamily: 'var(--font-serif), serif', fontStyle: 'italic', fontSize: 12, color: '#888', marginBottom: 18, animation: 'fadeSlide 420ms ease 60ms both' }}>
        Three angles considered —
      </div>

      {/* SVG — vertical branch + 3 branch curves */}
      <svg width="100%" height={totalHeight} viewBox={`0 0 320 ${totalHeight}`} preserveAspectRatio="xMinYMin meet"
        style={{ position: 'absolute', top: 50, left: 0, pointerEvents: 'none', overflow: 'visible' }}>
        <circle cx="20" cy="6" r="5" fill={RED} opacity="0.92" style={{ animation: 'popIn 320ms ease 100ms both' }} />
        <circle cx="20" cy="6" r="2" fill={PAPER} />
        <path d={`M 20 12 Q 22 ${TICKET_GAP * 0.5}, 18 ${TICKET_GAP * 1.0} T 20 ${TICKET_GAP * 2.0} T 18 ${TICKET_GAP * 2.6}`}
          stroke={RED_SOFT} strokeWidth="1.4" fill="none" strokeLinecap="round" strokeDasharray="600" strokeDashoffset="600"
          style={{ animation: 'drawLine 900ms ease 200ms forwards' }} />
        {options.slice(0, 3).map((_, i) => {
          const y = 40 + i * TICKET_GAP
          const startX = i === 2 ? 18 : 20
          return (
            <g key={i}>
              <path d={`M ${startX} ${y} Q 50 ${y + 4}, 80 ${y + 8} T 110 ${y + 6}`}
                stroke={RED_SOFT} strokeWidth="1.3" fill="none" strokeLinecap="round"
                strokeDasharray="180" strokeDashoffset="180"
                style={{ animation: `drawLine 520ms ease ${400 + i * 220}ms forwards` }} />
              <path d={`M 105 ${y + 3} L 112 ${y + 6} L 105 ${y + 9}`}
                stroke={RED_SOFT} strokeWidth="1.2" fill="none" strokeLinecap="round" strokeLinejoin="round"
                opacity="0" style={{ animation: `fadeIn 200ms ease ${900 + i * 220}ms forwards` }} />
            </g>
          )
        })}
      </svg>

      {/* Three tickets */}
      <div style={{ position: 'relative', marginTop: 56 }}>
        {options.slice(0, 3).map((opt, i) => (
          <div key={i} style={{
            position: 'absolute', top: i * TICKET_GAP - 30, left: 120, right: 0,
            animation: `ticketIn 520ms cubic-bezier(0.16,1,0.3,1) ${700 + i * 220}ms both`,
          }}>
            <Ticket index={i + 1} text={opt} onApply={() => onApply(opt)} rotation={rotFor(opt + String(i), 1.8)} />
          </div>
        ))}
      </div>

      <style>{`
        @keyframes fadeSlide { from{opacity:0;transform:translateY(-6px)} to{opacity:1;transform:translateY(0)} }
        @keyframes popIn { from{opacity:0;transform:scale(0);transform-origin:center} to{opacity:0.92;transform:scale(1)} }
        @keyframes drawLine { to{stroke-dashoffset:0} }
        @keyframes fadeIn { to{opacity:1} }
        @keyframes ticketIn {
          0%{opacity:0;transform:translateX(30px) translateY(-8px) scale(0.85)}
          70%{opacity:1;transform:translateX(-3px) translateY(0) scale(1.02)}
          100%{opacity:1;transform:translateX(0) translateY(0) scale(1)}
        }
      `}</style>
    </div>
  )
}

/* ─── Single ticket shape (SVG) ──────────────────────────── */

function Ticket({ index, text, onApply, rotation }: { index: number; text: string; onApply: () => void; rotation: number }) {
  return (
    <div style={{
      transform: `rotate(${rotation}deg)`, transformOrigin: 'left center',
      filter: 'drop-shadow(0 8px 18px rgba(0,0,0,0.10)) drop-shadow(0 2px 4px rgba(0,0,0,0.06))',
    }}>
      <svg width="100%" height="120" viewBox="0 0 220 120" preserveAspectRatio="none" style={{ display: 'block', overflow: 'visible' }}>
        <path
          d="M 4 2 L 218 2 L 218 118 L 5 118 L 3 110 L 6 100 L 2 88 L 5 76 L 3 64 L 6 52 L 2 40 L 5 28 L 3 16 L 4 8 Z"
          fill={PAPER} stroke="rgba(0,0,0,0.06)" strokeWidth="0.5" />
        <line x1="190" y1="6" x2="190" y2="114" stroke="rgba(192,57,43,0.35)" strokeWidth="0.6" strokeDasharray="2,3" />
      </svg>
      <div style={{
        position: 'relative', marginTop: -120, padding: '14px 38px 14px 18px', height: 120,
        display: 'flex', flexDirection: 'column', justifyContent: 'space-between',
      }}>
        <div style={{ display: 'flex', alignItems: 'baseline', gap: 10, marginBottom: 4 }}>
          <span style={{ fontFamily: 'var(--font-mono), monospace', fontSize: 9, color: RED, letterSpacing: '0.18em', fontWeight: 600 }}>№{String(index).padStart(2, '0')}</span>
          <div style={{ flex: 1, height: 0.5, background: 'rgba(192,57,43,0.30)' }} />
        </div>
        <div style={{
          fontFamily: 'var(--font-serif), serif', fontSize: 13, color: INK, lineHeight: 1.4, flex: 1,
          overflow: 'hidden', display: '-webkit-box', WebkitLineClamp: 3, WebkitBoxOrient: 'vertical',
        }}>{text}</div>
        <button onClick={onApply} style={{ background: 'transparent', border: 'none', padding: 0, marginTop: 4, fontFamily: 'var(--font-serif), serif', fontStyle: 'italic', fontSize: 12, cursor: 'pointer', color: RED, textAlign: 'left', alignSelf: 'flex-start' }}>
          ⊳ ink this in
        </button>
      </div>
    </div>
  )
}

/* ─── Single ticket (refine / critique) ──────────────────── */

function SingleTicket({ label, body, showApply, onApply, onClose }: { label: string; body: string; showApply: boolean; onApply: () => void; onClose: () => void }) {
  const rotation = useMemo(() => rotFor(body, 1.8), [body])

  return (
    <div style={{
      position: 'relative', transform: `rotate(${rotation}deg)`, transformOrigin: 'top left',
      animation: 'ticketIn 520ms cubic-bezier(0.16,1,0.3,1)',
      filter: 'drop-shadow(0 10px 22px rgba(0,0,0,0.10)) drop-shadow(0 2px 6px rgba(0,0,0,0.06))',
    }}>
      <button onClick={onClose} style={{ position: 'absolute', top: 6, right: 8, background: 'transparent', border: 'none', cursor: 'pointer', color: '#999', fontSize: 16, lineHeight: 1, padding: 4, zIndex: 5 }}>✕</button>
      <svg width="100%" height="auto" viewBox="0 0 300 200" preserveAspectRatio="none" style={{ display: 'block', width: '100%' }}>
        <path
          d="M 6 3 L 297 3 L 297 197 L 7 197 L 4 182 L 7 162 L 3 142 L 6 122 L 4 102 L 7 82 L 3 62 L 6 42 L 4 22 L 6 8 Z"
          fill={PAPER} stroke="rgba(0,0,0,0.06)" strokeWidth="0.5" />
        <line x1="260" y1="8" x2="260" y2="192" stroke="rgba(192,57,43,0.35)" strokeWidth="0.6" strokeDasharray="2,3" />
      </svg>
      <div style={{ position: 'absolute', top: 0, left: 0, right: 0, bottom: 0, padding: '20px 52px 18px 22px', display: 'flex', flexDirection: 'column' }}>
        <div style={{ fontFamily: 'var(--font-mono), monospace', fontSize: 8, letterSpacing: '0.28em', color: RED, fontWeight: 600, marginBottom: 12, paddingBottom: 8, borderBottom: '0.5px dashed rgba(192,57,43,0.40)' }}>
          {label}
        </div>
        <div style={{ fontFamily: 'var(--font-serif), serif', fontSize: 14, color: INK, lineHeight: 1.55, fontStyle: 'italic', flex: 1, whiteSpace: 'pre-wrap', overflow: 'hidden' }}>
          {body}
        </div>
        {showApply && (
          <button onClick={onApply} style={{ background: RED, color: PAPER, border: 'none', padding: '7px 14px', marginTop: 12, fontFamily: 'var(--font-mono), monospace', fontSize: 9, letterSpacing: '0.20em', cursor: 'pointer', fontWeight: 600, alignSelf: 'flex-start' }}>
            ⊳ INK THIS IN
          </button>
        )}
      </div>
    </div>
  )
}
