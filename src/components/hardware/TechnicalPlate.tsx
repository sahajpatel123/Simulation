'use client'

import React, { useState, useEffect } from 'react'

interface Layer {
  id: string
  label: string
  sublabel: string
  fill: string
  rightFace: string
  leftFace: string
  textColor: string
  yOffset: number
}

interface TechnicalPlateProps {
  productName?: string
  category?: string
  layers?: Layer[]
  hasSpec?: boolean
  onRunPhysics?: () => void
  onBack?: () => void
}

const DEFAULT_LAYERS: Layer[] = [
  {
    id: 'glass',
    label: 'COVER GLASS',
    sublabel: 'Gorilla Glass 3 · 2.5D · 0.7mm',
    fill: 'rgba(170,205,235,0.30)',
    rightFace: 'rgba(150,188,220,0.20)',
    leftFace: 'rgba(160,196,228,0.25)',
    textColor: '#2266aa',
    yOffset: 0,
  },
  {
    id: 'display',
    label: 'DISPLAY MODULE',
    sublabel: 'AMOLED · 1.4in · 454ppi',
    fill: '#22324e',
    rightFace: '#182540',
    leftFace: '#1c2844',
    textColor: '#7788cc',
    yOffset: 64,
  },
  {
    id: 'pcb',
    label: 'MAIN PCB',
    sublabel: 'FR4 · 4-Layer · ARM Cortex',
    fill: '#1a2a4a',
    rightFace: '#121f38',
    leftFace: '#162240',
    textColor: '#5577bb',
    yOffset: 128,
  },
  {
    id: 'battery',
    label: 'BATTERY CELL',
    sublabel: 'LiPo · 3.7V · 300mAh',
    fill: '#b8d4b8',
    rightFace: '#a4c0a4',
    leftFace: '#acc8ac',
    textColor: '#2d5a2d',
    yOffset: 192,
  },
  {
    id: 'shell',
    label: 'ENCLOSURE SHELL',
    sublabel: 'ABS · 1.2mm',
    fill: '#e0dbd0',
    rightFace: '#ccc8be',
    leftFace: '#d4d0c6',
    textColor: '#555',
    yOffset: 256,
  },
]

const CREAM = '#f5f0e8'
const DARK  = '#111111'
const RED   = '#c0392b'

export function TechnicalPlate({
  productName = '—',
  category = '—',
  layers = DEFAULT_LAYERS,
  hasSpec = false,
  onRunPhysics,
  onBack,
}: TechnicalPlateProps) {
  const [dark, setDark] = useState(false)
  const [revealedCount, setRevealedCount] = useState(0)
  const [hoveredLayer, setHoveredLayer] = useState<number | null>(null)

  useEffect(() => {
    if (!hasSpec) {
      setRevealedCount(0)
      return
    }
    let i = 0
    const interval = setInterval(() => {
      i += 1
      setRevealedCount(i)
      if (i >= layers.length) clearInterval(interval)
    }, 110)
    return () => clearInterval(interval)
  }, [hasSpec, layers.length])

  const bg      = dark ? DARK  : CREAM
  const gridCol = dark
    ? 'rgba(255,255,255,0.06)'
    : 'rgba(140,135,125,0.22)'
  const dimCol  = dark ? '#555' : '#c4bfb4'
  const lblCol  = dark ? '#888' : '#bbb'
  const regCol  = dark ? '#444' : '#bbb'
  const callCol = dark ? '#aaa' : '#555'
  const callSub = dark ? '#666' : '#aaa'
  const tbBg    = dark
    ? 'rgba(20,20,20,0.95)'
    : 'rgba(245,240,232,0.95)'
  const tbBorder = dark ? '#333' : '#c8c3b8'
  const tbLbl   = dark ? '#555' : '#bbb'
  const tbVal   = dark ? '#ccc' : '#1a1a1a'

  const today = new Date().toLocaleDateString('en-GB', {
    day: '2-digit',
    month: 'short',
    year: 'numeric',
  }).toUpperCase()

  return (
    <div
      style={{
        position: 'relative',
        flex: 1,
        padding: '24px',
        paddingBottom: '76px',
        background: CREAM,
        transition: 'background 0.35s ease',
        overflow: 'hidden',
      }}
    >
      <div
        style={{
          position: 'relative',
          width: '100%',
          height: '100%',
          background: bg,
          border: '1px solid #1a1a1a',
          boxShadow: '0 1px 3px rgba(0,0,0,0.04), 0 8px 24px rgba(0,0,0,0.06)',
          overflow: 'hidden',
        }}
      >
        {/* Grid */}
        <div
          style={{
            position: 'absolute',
            inset: 0,
            backgroundImage: `
              linear-gradient(${gridCol} 1px, transparent 1px),
              linear-gradient(90deg, ${gridCol} 1px, transparent 1px)
            `,
            backgroundSize: '24px 24px',
            pointerEvents: 'none',
          }}
        />

        {/* Registration marks */}
        {(['tl', 'tr', 'bl', 'br'] as const).map(pos => (
          <div
            key={pos}
            style={{
              position: 'absolute',
              width: 14,
              height: 14,
              top:    pos.startsWith('t') ? 10 : undefined,
              bottom: pos.startsWith('b') ? 46 : undefined,
              left:   pos.endsWith('l')   ? 10 : undefined,
              right:  pos.endsWith('r')   ? 10 : undefined,
              borderTop:    pos.startsWith('t') ? `1px solid ${regCol}` : undefined,
              borderBottom: pos.startsWith('b') ? `1px solid ${regCol}` : undefined,
              borderLeft:   pos.endsWith('l')   ? `1px solid ${regCol}` : undefined,
              borderRight:  pos.endsWith('r')   ? `1px solid ${regCol}` : undefined,
            }}
          />
        ))}

        {/* Plate label */}
        <div
          style={{
            position: 'absolute',
            top: 13,
            left: '50%',
            transform: 'translateX(-50%)',
            fontFamily: "'Courier New', monospace",
            fontSize: 7,
            letterSpacing: '0.18em',
            color: RED,
            whiteSpace: 'nowrap',
            pointerEvents: 'none',
          }}
        >
          STANDING TYPE · HARDWARE ATELIER
        </div>

        <div
          style={{
            position: 'absolute',
            top: 26,
            right: 16,
            display: 'flex',
            flexDirection: 'column',
            gap: 22,
            alignItems: 'flex-end',
            zIndex: 5,
          }}
        >
          <button
            onClick={() => setDark(d => !d)}
            title={dark ? 'Switch to daylight' : 'Switch to pressroom'}
            type="button"
            style={{
              background: 'transparent',
              border: `0.5px solid ${dark ? '#444' : '#c8c3b8'}`,
              padding: '4px 9px',
              cursor: 'pointer',
              fontFamily: "'Courier New', monospace",
              fontSize: 6.5,
              letterSpacing: '0.12em',
              color: dark ? '#888' : '#aaa',
              display: 'flex',
              alignItems: 'center',
              gap: 5,
              transition: 'all 0.2s ease',
            }}
          >
            <span
              style={{
                display: 'inline-block',
                width: 6,
                height: 6,
                borderRadius: '50%',
                background: dark ? '#f5f0e8' : '#1a1a1a',
                transition: 'background 0.2s ease',
              }}
            />
            {dark ? 'DAYLIGHT' : 'PRESSROOM'}
          </button>
        </div>

        {!hasSpec ? (
          <div style={{
            position: 'absolute',
            top: '50%',
            left: '50%',
            transform: 'translate(-50%, -50%)',
            textAlign: 'center',
            pointerEvents: 'none',
          }}>
            <div style={{
              fontFamily: "'Courier New', monospace",
              fontSize: 9,
              letterSpacing: '0.22em',
              color: '#c0392b',
              marginBottom: 12,
            }}>
              AWAITING PRESS
            </div>
            <div style={{
              fontFamily: 'Georgia, serif',
              fontStyle: 'italic',
              fontSize: 14,
              color: '#888',
            }}>
              File the specification sheet to begin.
            </div>
          </div>
        ) : (
          <div
            style={{
              position: 'absolute',
              top: '50%',
              left: '50%',
              transform: 'translate(-50%, -50%)',
              pointerEvents: 'none',
            }}
          >
            <svg
              width={400}
              height={460}
              viewBox="0 0 360 400"
              fill="none"
              xmlns="http://www.w3.org/2000/svg"
              style={{ pointerEvents: 'visible' }}
            >
              {layers.map((layer, idx) => {
                const y = layer.yOffset
                const cx = 168 - idx * 6
                const w  = 56
                const isHovered = hoveredLayer === idx
                return (
                  <g
                    key={layer.id}
                    onMouseEnter={() => setHoveredLayer(idx)}
                    onMouseLeave={() => setHoveredLayer(null)}
                    style={{
                      cursor: 'pointer',
                      opacity: idx < revealedCount ? 1 : 0,
                      transition: 'opacity 0.4s ease, transform 0.4s ease',
                      transform: idx < revealedCount ? 'translateY(0)' : 'translateY(-8px)',
                      transformOrigin: 'center',
                      transformBox: 'fill-box',
                    }}
                  >
                    {idx < layers.length - 1 && (
                      <line
                        x1={cx}
                        y1={y + 56 - 4}
                        x2={cx}
                        y2={y + 56 + 8}
                        stroke={RED}
                        strokeWidth={0.5}
                        strokeDasharray="2,2"
                      />
                    )}
                    {/* Top face */}
                    <path
                      d={`M${cx - w} ${y + 28} L${cx} ${y} L${cx + w} ${y + 28} L${cx} ${y + 56} Z`}
                      fill={layer.fill}
                      stroke={dark ? '#444' : '#1a1a1a'}
                      strokeWidth={0.8}
                    />
                    {/* Right face */}
                    <path
                      d={`M${cx + w} ${y + 28} L${cx + w} ${y + 40} L${cx} ${y + 68} L${cx} ${y + 56} Z`}
                      fill={layer.rightFace}
                      stroke={dark ? '#444' : '#1a1a1a'}
                      strokeWidth={0.8}
                    />
                    {/* Left face */}
                    <path
                      d={`M${cx - w} ${y + 28} L${cx - w} ${y + 40} L${cx} ${y + 68} L${cx} ${y + 56} Z`}
                      fill={layer.leftFace}
                      stroke={dark ? '#444' : '#1a1a1a'}
                      strokeWidth={0.8}
                    />
                    {/* Label */}
                    <text
                      x={cx}
                      y={y + 33}
                      fontFamily="'Courier New', monospace"
                      fontSize={6.5}
                      fill={layer.textColor}
                      textAnchor="middle"
                      style={{ pointerEvents: 'none' }}
                    >
                      {layer.label}
                    </text>
                    <text
                      x={cx}
                      y={y + 43}
                      fontFamily="'Courier New', monospace"
                      fontSize={5}
                      fill={layer.textColor}
                      opacity={0.7}
                      textAnchor="middle"
                      style={{ pointerEvents: 'none' }}
                    >
                      {layer.sublabel}
                    </text>
                    {/* Left callout */}
                    <circle
                      cx={cx - w + 2}
                      cy={y + 28}
                      r={2}
                      fill={RED}
                      style={{ opacity: isHovered ? 1 : 0, transition: 'opacity 0.3s ease' }}
                    />
                    <line
                      x1={cx - w + 2}
                      y1={y + 28}
                      x2={38}
                      y2={y + 42}
                      stroke={RED}
                      strokeWidth={0.4}
                      style={{ opacity: isHovered ? 1 : 0, transition: 'opacity 0.3s ease' }}
                    />
                    <text
                      x={2}
                      y={y + 46}
                      fontFamily="'Courier New', monospace"
                      fontSize={6}
                      fill={callCol}
                      style={{ opacity: isHovered ? 1 : 0, transition: 'opacity 0.3s ease' }}
                    >
                      {String(idx + 1).padStart(2, '0')} · {layer.label}
                    </text>
                    <text
                      x={2}
                      y={y + 55}
                      fontFamily="'Courier New', monospace"
                      fontSize={5}
                      fill={callSub}
                      style={{ opacity: isHovered ? 1 : 0, transition: 'opacity 0.3s ease' }}
                    >
                      {layer.sublabel}
                    </text>
                  </g>
                )
              })}

              {/* Width dimension */}
              <line x1={96} y1={308} x2={208} y2={308} stroke={dimCol} strokeWidth={0.5} />
              <line x1={96} y1={302} x2={96}  y2={314} stroke={dimCol} strokeWidth={0.5} />
              <line x1={208} y1={302} x2={208} y2={314} stroke={dimCol} strokeWidth={0.5} />
              <text
                x={152} y={322}
                fontFamily="'Courier New', monospace"
                fontSize={6}
                fill={dimCol}
                textAnchor="middle"
              >
                W · 44mm
              </text>
            </svg>
          </div>
        )}

        {/* Title block */}
        <div
          style={{
            position: 'absolute',
            bottom: 46,
            right: 14,
            border: `0.5px solid ${tbBorder}`,
            background: tbBg,
            padding: '6px 10px',
            minWidth: 138,
            transition: 'background 0.35s, border-color 0.35s',
          }}
        >
          {([
            ['PROJECT',  productName],
            ['CATEGORY', category],
          ] as [string, string][]).map(([l, v]) => (
            <div key={l} style={{ display: 'flex', justifyContent: 'space-between', gap: 14, marginBottom: 2 }}>
              <span style={{ fontFamily: "'Courier New', monospace", fontSize: 6, letterSpacing: '0.08em', color: tbLbl }}>{l}</span>
              <span style={{ fontFamily: "'Courier New', monospace", fontSize: 6, color: tbVal, textAlign: 'right' }}>{v}</span>
            </div>
          ))}
          <hr style={{ border: 'none', borderTop: `0.5px solid ${tbBorder}`, margin: '3px 0' }} />
          {([
            ['COMPONENTS', hasSpec ? String(layers.length) : '—'],
            ['EST. MASS', hasSpec ? '48g' : '—'],
          ] as [string, string][]).map(([l, v]) => (
            <div key={l} style={{ display: 'flex', justifyContent: 'space-between', gap: 14, marginBottom: 2 }}>
              <span style={{ fontFamily: "'Courier New', monospace", fontSize: 6, letterSpacing: '0.08em', color: tbLbl }}>{l}</span>
              <span style={{ fontFamily: "'Courier New', monospace", fontSize: 6, color: tbVal, textAlign: 'right' }}>{v}</span>
            </div>
          ))}
          <hr style={{ border: 'none', borderTop: `0.5px solid ${tbBorder}`, margin: '3px 0' }} />
          {([
            ['SCALE',   'NTS · EXPLODED'],
            ['EDITION', 'HARDWARE ATELIER'],
            ['FILED',   hasSpec ? today : '—'],
          ] as [string, string][]).map(([l, v]) => (
            <div key={l} style={{ display: 'flex', justifyContent: 'space-between', gap: 14, marginBottom: 2 }}>
              <span style={{ fontFamily: "'Courier New', monospace", fontSize: 6, letterSpacing: '0.08em', color: tbLbl }}>{l}</span>
              <span style={{ fontFamily: "'Courier New', monospace", fontSize: 6, color: tbVal, textAlign: 'right' }}>{v}</span>
            </div>
          ))}
        </div>
      </div>

      <div style={{
        position: 'absolute',
        bottom: 0,
        left: 0,
        right: 0,
        height: 52,
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'space-between',
        padding: '0 24px',
        background: 'transparent',
      }}>
        {/* LEFT — Back to dossier */}
        <button onClick={onBack} style={{
          background: 'transparent',
          border: '0.5px solid #c8c3b8',
          padding: '8px 16px',
          fontFamily: "'Courier New', monospace",
          fontSize: 10,
          letterSpacing: '0.12em',
          color: '#1a1a1a',
          cursor: 'pointer',
          display: 'flex',
          alignItems: 'center',
          gap: 8,
        }}>
          ← BACK TO DOSSIER
        </button>

        {/* CENTER — view toggle */}
        <div style={{
          display: 'flex',
          border: '0.5px solid #c8c3b8',
        }}>
          <button style={{
            background: '#1a1a1a',
            color: '#f5f0e8',
            padding: '8px 18px',
            border: 'none',
            fontFamily: "'Courier New', monospace",
            fontSize: 10,
            letterSpacing: '0.14em',
            cursor: 'pointer',
          }}>
            ⊞ BLUEPRINT
          </button>
          <button style={{
            background: 'transparent',
            color: '#1a1a1a',
            padding: '8px 18px',
            border: 'none',
            borderLeft: '0.5px solid #c8c3b8',
            fontFamily: "'Courier New', monospace",
            fontSize: 10,
            letterSpacing: '0.14em',
            cursor: 'pointer',
          }}>
            ◇ DIAGRAM
          </button>
        </div>

        {/* RIGHT — primary action */}
        <button 
          onClick={onRunPhysics}
          disabled={!hasSpec}
          style={{
            background: hasSpec ? '#1a1a1a' : '#888',
            color: '#f5f0e8',
            border: 'none',
            padding: '10px 20px',
            fontFamily: "'Courier New', monospace",
            fontSize: 10,
            letterSpacing: '0.14em',
            cursor: hasSpec ? 'pointer' : 'not-allowed',
            display: 'flex',
            alignItems: 'center',
            gap: 8,
          }}>
          RUN PHYSICS →
        </button>
      </div>
    </div>
  )
}
