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
const RED_FAINT = 'rgba(192,57,43,0.30)'
const PAPER = '#fdf8ed'
const INK = '#1a1a1a'

export default function MarginNote({ mode, result, onClose, onApply }: MarginNoteProps) {
  if (mode === 'suggest' && Array.isArray(result)) {
    return <RadialConstellation options={result.slice(0, 3)} onClose={onClose} onApply={onApply} />
  }

  if (mode === 'refine' && typeof result === 'string') {
    return <SingleTicket label="A REFINED LINE" body={result} showApply onApply={() => onApply(result)} onClose={onClose} />
  }

  return <SingleTicket label="THE EDITOR'S MARK" body={typeof result === 'string' ? result : ''} showApply={false} onApply={() => {}} onClose={onClose} />
}

/* ─── RADIAL CONSTELLATION ──────────────────────────────── */

function RadialConstellation({ options, onClose, onApply }: { options: string[]; onClose: () => void; onApply: (v: string) => void }) {
  const ANCHOR_X = 30
  const ANCHOR_Y = 200

  const positions = [
    { x: 200, y: 70, rot: -8, label: '01' },
    { x: 230, y: 200, rot: 2, label: '02' },
    { x: 200, y: 330, rot: 6, label: '03' },
  ]

  return (
    <div style={{ position: 'relative', minHeight: 420, width: '100%' }}>
      <button onClick={onClose} style={{ position: 'absolute', top: 0, right: 0, background: 'transparent', border: 'none', cursor: 'pointer', color: '#999', fontSize: 18, lineHeight: 1, padding: 4, zIndex: 20 }} aria-label="Dismiss">✕</button>

      <div style={{ fontFamily: 'var(--font-mono), monospace', fontSize: 8, letterSpacing: '0.28em', color: RED, fontWeight: 600, marginBottom: 6, animation: 'fadeSlide 380ms ease both' }}>
        ── THE EDITOR'S CONSTELLATION ──
      </div>
      <div style={{ fontFamily: 'var(--font-serif), serif', fontStyle: 'italic', fontSize: 12, color: '#888', marginBottom: 18, animation: 'fadeSlide 420ms ease 60ms both' }}>
        Three angles, drawn outward —
      </div>

      <svg width="100%" height="420" viewBox="0 0 380 420" preserveAspectRatio="xMinYMin meet"
        style={{ position: 'absolute', top: 50, left: 0, pointerEvents: 'none', overflow: 'visible' }}>
        <circle cx={ANCHOR_X} cy={ANCHOR_Y} r="7" fill={RED} opacity="0.92" style={{ animation: 'popIn 360ms ease 100ms both' }} />
        <circle cx={ANCHOR_X} cy={ANCHOR_Y} r="2.5" fill={PAPER} style={{ animation: 'popIn 360ms ease 180ms both' }} />
        {positions.map((p, i) => {
          const dx = p.x - ANCHOR_X
          const dy = p.y - ANCHOR_Y
          const midX = ANCHOR_X + dx * 0.45
          const midY = ANCHOR_Y + dy * 0.55
          const offsetX = -dy * 0.08
          const offsetY = dx * 0.08
          return (
            <g key={i}>
              <path d={`M ${ANCHOR_X} ${ANCHOR_Y} Q ${midX + offsetX} ${midY + offsetY}, ${p.x - 30} ${p.y}`}
                stroke={RED_SOFT} strokeWidth="1.4" fill="none" strokeLinecap="round"
                strokeDasharray="300" strokeDashoffset="300"
                style={{ animation: `drawLine 640ms ease ${350 + i * 180}ms forwards` }} />
              <path d={`M ${p.x - 35} ${p.y - 4} L ${p.x - 28} ${p.y} L ${p.x - 35} ${p.y + 4}`}
                stroke={RED_SOFT} strokeWidth="1.2" fill="none" strokeLinecap="round" strokeLinejoin="round"
                opacity="0" style={{ animation: `fadeIn 200ms ease ${900 + i * 180}ms forwards` }} />
            </g>
          )
        })}
      </svg>

      {options.map((opt, i) => {
        const p = positions[i]
        return (
          <div key={i} style={{
            position: 'absolute', top: 50 + p.y - 55, left: p.x - 20, width: 200,
            animation: `ticketIn 540ms cubic-bezier(0.16,1,0.3,1) ${750 + i * 180}ms both`,
          }}>
            <Ticket index={i + 1} text={opt} onApply={() => onApply(opt)} rotation={p.rot + rotFor(opt, 1.5)} />
          </div>
        )
      })}

      <style>{`
        @keyframes fadeSlide { from{opacity:0;transform:translateY(-6px)} to{opacity:1;transform:translateY(0)} }
        @keyframes popIn { from{opacity:0;transform:scale(0);transform-origin:center} to{opacity:0.92;transform:scale(1)} }
        @keyframes drawLine { to{stroke-dashoffset:0} }
        @keyframes fadeIn { to{opacity:1} }
        @keyframes ticketIn { 0%{opacity:0;transform:translateX(-20px) scale(0.85)} 70%{opacity:1;transform:translateX(2px) scale(1.02)} 100%{opacity:1;transform:translateX(0) scale(1)} }
      `}</style>
    </div>
  )
}

/* ─── THE TICKET ──────────────────────────────────────────── */

function Ticket({ index, text, onApply, rotation }: { index: number; text: string; onApply: () => void; rotation: number }) {
  return (
    <div style={{
      transform: `rotate(${rotation}deg)`, transformOrigin: 'center center',
      filter: 'drop-shadow(0 10px 22px rgba(0,0,0,0.12)) drop-shadow(0 3px 6px rgba(0,0,0,0.08))',
    }}>
      <svg width="100%" height="110" viewBox="0 0 200 110" preserveAspectRatio="none" style={{ display: 'block', overflow: 'visible' }}>
        <path d="M 4 2 L 198 2 L 198 108 L 5 108 L 3 100 L 6 90 L 2 78 L 5 66 L 3 54 L 6 42 L 2 30 L 5 18 L 3 8 Z"
          fill={PAPER} stroke="rgba(0,0,0,0.06)" strokeWidth="0.5" />
        <line x1="172" y1="6" x2="172" y2="104" stroke={RED_FAINT} strokeWidth="0.6" strokeDasharray="2,3" />
      </svg>
      <div style={{ position: 'relative', marginTop: -110, padding: '12px 36px 12px 16px', height: 110, display: 'flex', flexDirection: 'column', justifyContent: 'space-between' }}>
        <div style={{ display: 'flex', alignItems: 'baseline', gap: 8, marginBottom: 2 }}>
          <span style={{ fontFamily: 'var(--font-mono), monospace', fontSize: 9, color: RED, letterSpacing: '0.18em', fontWeight: 600 }}>№{String(index).padStart(2, '0')}</span>
          <div style={{ flex: 1, height: 0.5, background: RED_FAINT }} />
        </div>
        <div style={{ fontFamily: 'var(--font-serif), serif', fontSize: 13, color: INK, lineHeight: 1.4, flex: 1, overflow: 'hidden', display: '-webkit-box', WebkitLineClamp: 3, WebkitBoxOrient: 'vertical' }}>{text}</div>
        <button onClick={onApply} style={{ background: 'transparent', border: 'none', padding: 0, marginTop: 4, fontFamily: 'var(--font-serif), serif', fontStyle: 'italic', fontSize: 12, cursor: 'pointer', color: RED, textAlign: 'left', alignSelf: 'flex-start' }}>
          ⊳ ink this in
        </button>
      </div>
    </div>
  )
}

/* ─── SINGLE TICKET (refine / critique) ──────────────────── */

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
        <path d="M 6 3 L 297 3 L 297 197 L 7 197 L 4 182 L 7 162 L 3 142 L 6 122 L 4 102 L 7 82 L 3 62 L 6 42 L 4 22 L 6 8 Z" fill={PAPER} stroke="rgba(0,0,0,0.06)" strokeWidth="0.5" />
        <line x1="260" y1="8" x2="260" y2="192" stroke={RED_FAINT} strokeWidth="0.6" strokeDasharray="2,3" />
      </svg>
      <div style={{ position: 'absolute', top: 0, left: 0, right: 0, bottom: 0, padding: '20px 52px 18px 22px', display: 'flex', flexDirection: 'column' }}>
        <div style={{ fontFamily: 'var(--font-mono), monospace', fontSize: 8, letterSpacing: '0.28em', color: RED, fontWeight: 600, marginBottom: 12, paddingBottom: 8, borderBottom: `0.5px dashed ${RED_FAINT}` }}>
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
