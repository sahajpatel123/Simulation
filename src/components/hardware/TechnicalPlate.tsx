'use client'

import React, { useState } from 'react'

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
    yOffset: 52,
  },
  {
    id: 'pcb',
    label: 'MAIN PCB',
    sublabel: 'FR4 · 4-Layer · ARM Cortex',
    fill: '#1a2a4a',
    rightFace: '#121f38',
    leftFace: '#162240',
    textColor: '#5577bb',
    yOffset: 106,
  },
  {
    id: 'battery',
    label: 'BATTERY CELL',
    sublabel: 'LiPo · 3.7V · 300mAh',
    fill: '#b8d4b8',
    rightFace: '#a4c0a4',
    leftFace: '#acc8ac',
    textColor: '#2d5a2d',
    yOffset: 162,
  },
  {
    id: 'shell',
    label: 'ENCLOSURE SHELL',
    sublabel: 'ABS · 1.2mm',
    fill: '#e0dbd0',
    rightFace: '#ccc8be',
    leftFace: '#d4d0c6',
    textColor: '#555',
    yOffset: 214,
  },
]

const CREAM = '#f5f0e8'
const DARK  = '#111111'
const RED   = '#c0392b'

export function TechnicalPlate({
  productName = '—',
  category = '—',
  layers = DEFAULT_LAYERS,
}: TechnicalPlateProps) {
  const [dark, setDark] = useState(false)

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
        background: bg,
        overflow: 'hidden',
        transition: 'background 0.35s ease',
        border: dark ? '1px solid #1a1a1a' : 'none',
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

      {/* Dark mode toggle */}
      <button
        onClick={() => setDark(d => !d)}
        title={dark ? 'Switch to daylight' : 'Switch to pressroom'}
        style={{
          position: 'absolute',
          top: 28,
          right: 14,
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
          zIndex: 10,
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

      {/* Component count */}
      <div
        style={{
          position: 'absolute',
          top: 56,
          right: 14,
          textAlign: 'right',
        }}
      >
        <div style={{
          fontFamily: "'Courier New', monospace",
          fontSize: 6.5,
          letterSpacing: '0.1em',
          color: lblCol,
        }}>
          COMPONENTS
        </div>
        <div style={{
          fontFamily: 'Georgia, serif',
          fontSize: 28,
          fontWeight: 'bold',
          color: dark ? '#f5f0e8' : '#1a1a1a',
          lineHeight: 1,
        }}>
          {layers.length}
        </div>
        <div style={{
          fontFamily: "'Courier New', monospace",
          fontSize: 6.5,
          color: RED,
          letterSpacing: '0.1em',
        }}>
          LAYERS · EXPLODED
        </div>
      </div>

      {/* Mass */}
      <div
        style={{
          position: 'absolute',
          top: 118,
          right: 14,
          textAlign: 'right',
        }}
      >
        <div style={{
          fontFamily: "'Courier New', monospace",
          fontSize: 6.5,
          letterSpacing: '0.1em',
          color: lblCol,
          marginBottom: 2,
        }}>
          EST. MASS
        </div>
        <div style={{
          fontFamily: "'Courier New', monospace",
          fontSize: 13,
          fontWeight: 'bold',
          color: dark ? '#f5f0e8' : '#1a1a1a',
        }}>
          48g
        </div>
      </div>

      {/* Isometric SVG diagram */}
      <div
        style={{
          position: 'absolute',
          top: '50%',
          left: '44%',
          transform: 'translate(-50%, -52%)',
          pointerEvents: 'none',
        }}
      >
        <svg
          width={320}
          height={340}
          viewBox="0 0 320 340"
          fill="none"
          xmlns="http://www.w3.org/2000/svg"
        >
          {layers.map((layer, idx) => {
            const y = layer.yOffset
            const cx = 168 - idx * 6
            const w  = 56
            return (
              <g key={layer.id}>
                {idx < layers.length - 1 && (
                  <line
                    x1={cx}
                    y1={y + 52 - 4}
                    x2={cx}
                    y2={y + 52 + 16}
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
                >
                  {layer.sublabel}
                </text>
                {/* Left callout */}
                <circle
                  cx={cx - w + 2}
                  cy={y + 28}
                  r={2}
                  fill={RED}
                />
                <line
                  x1={cx - w + 2}
                  y1={y + 28}
                  x2={38}
                  y2={y + 42}
                  stroke={RED}
                  strokeWidth={0.4}
                />
                <text
                  x={2}
                  y={y + 46}
                  fontFamily="'Courier New', monospace"
                  fontSize={6}
                  fill={callCol}
                >
                  {String(idx + 1).padStart(2, '0')} · {layer.label}
                </text>
                <text
                  x={2}
                  y={y + 55}
                  fontFamily="'Courier New', monospace"
                  fontSize={5}
                  fill={callSub}
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

          {/* Height dimension */}
          <line x1={268} y1={4}   x2={268} y2={284} stroke={dimCol} strokeWidth={0.5} />
          <line x1={262} y1={4}   x2={274} y2={4}   stroke={dimCol} strokeWidth={0.5} />
          <line x1={262} y1={284} x2={274} y2={284} stroke={dimCol} strokeWidth={0.5} />
          <text
            x={282}
            y={144}
            fontFamily="'Courier New', monospace"
            fontSize={6}
            fill={dimCol}
            textAnchor="middle"
            transform="rotate(90,282,144)"
          >
            H · 12mm TOTAL
          </text>
        </svg>
      </div>

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
          ['SCALE',   'NTS · EXPLODED'],
          ['EDITION', 'HARDWARE ATELIER'],
          ['FILED',   today],
        ] as [string, string][]).map(([l, v]) => (
          <div key={l} style={{ display: 'flex', justifyContent: 'space-between', gap: 14, marginBottom: 2 }}>
            <span style={{ fontFamily: "'Courier New', monospace", fontSize: 6, letterSpacing: '0.08em', color: tbLbl }}>{l}</span>
            <span style={{ fontFamily: "'Courier New', monospace", fontSize: 6, color: tbVal, textAlign: 'right' }}>{v}</span>
          </div>
        ))}
      </div>

      {/* Step strip */}
      <StepStrip dark={dark} />
    </div>
  )
}

const STEPS = [
  { num: 'I',   name: 'Geometry',    sub: 'THE FORM'      },
  { num: 'II',  name: 'Physics',     sub: 'STRESS · LOAD' },
  { num: 'III', name: 'Cost',        sub: 'MARGIN'        },
  { num: 'IV',  name: 'Simulation',  sub: '52 CLUSTERS'   },
  { num: 'V',   name: 'Competitive', sub: 'POSITION'      },
  { num: 'VI',  name: 'Report',      sub: 'FILED · PDF'   },
]

function StepStrip({ dark }: { dark: boolean }) {
  const [active, setActive] = useState(0)
  const borderCol = dark ? '#2a2a2a' : '#c8c3b8'
  const topBorder = dark ? '#2a2a2a' : '#1a1a1a'
  const inactBg   = dark ? '#111'    : '#f5f0e8'
  const inactNum  = dark ? '#555'    : '#999'
  const inactName = dark ? '#666'    : '#1a1a1a'
  const inactSub  = dark ? '#333'    : '#bbb'

  return (
    <div style={{
      position: 'absolute',
      bottom: 0,
      left: 0,
      right: 0,
      height: 36,
      borderTop: `1.5px solid ${topBorder}`,
      display: 'flex',
      transition: 'border-color 0.35s',
    }}>
      {STEPS.map((s, i) => {
        const isAct = i === active
        return (
          <div
            key={s.num}
            onClick={() => setActive(i)}
            style={{
              flex: 1,
              display: 'flex',
              flexDirection: 'column',
              alignItems: 'center',
              justifyContent: 'center',
              borderRight: i < STEPS.length - 1 ? `0.5px solid ${borderCol}` : 'none',
              cursor: 'pointer',
              padding: '3px 4px',
              background: isAct ? '#1a1a1a' : inactBg,
              transition: 'background 0.15s',
            }}
          >
            <div style={{
              fontFamily: "'Courier New', monospace",
              fontSize: 6.5,
              letterSpacing: '0.08em',
              color: isAct ? RED : inactNum,
              marginBottom: 1,
            }}>
              {s.num}
            </div>
            <div style={{
              fontFamily: "'Courier New', monospace",
              fontSize: 6.5,
              letterSpacing: '0.07em',
              color: isAct ? '#f5f0e8' : inactName,
              textAlign: 'center',
              textTransform: 'uppercase',
            }}>
              {s.name}
            </div>
            <div style={{
              fontFamily: "'Courier New', monospace",
              fontSize: 5.5,
              color: isAct ? '#666' : inactSub,
              letterSpacing: '0.05em',
              textAlign: 'center',
            }}>
              {s.sub}
            </div>
          </div>
        )
      })}
    </div>
  )
}
