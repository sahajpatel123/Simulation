'use client';

import React, { useState, useEffect, useRef } from 'react';

interface TechnicalPlateProps {
  productName?: string;
  category?: string;
  hasSpec?: boolean;
  onRunPhysics?: () => void;
  onBack?: () => void;
}

const RED = '#c0392b';

/** Uniform square graph paper inside the bordered drawing sheet only (not the page bench). */
const DRAWING_SHEET_GRID_STEP_PX = 12;

export function TechnicalPlate({
  productName = '—',
  category = '—',
  hasSpec = false,
  onRunPhysics,
  onBack,
}: TechnicalPlateProps) {
  const [dark, setDark] = useState(false);
  const [rotation, setRotation] = useState(0);
  const rafRef = useRef<number | null>(null);

  useEffect(() => {
    const animate = () => {
      setRotation(r => (r + 0.25) % 360);
      rafRef.current = requestAnimationFrame(animate);
    };
    rafRef.current = requestAnimationFrame(animate);
    return () => {
      if (rafRef.current) cancelAnimationFrame(rafRef.current);
    };
  }, []);

  const sheetBg     = dark ? '#0f0f0f' : '#f5f0e8';
  const sheetBorder = dark ? '#222'    : '#1a1a1a';
  const lblCol      = dark ? '#666'    : '#999';
  const valCol      = dark ? '#e8e4dc' : '#1a1a1a';
  const regCol      = dark ? '#3a3a3a' : '#999';
  const subtleText  = dark ? '#5a5a5a' : '#888';

  const today = new Date().toLocaleDateString('en-GB', {
    day: '2-digit', month: 'short', year: 'numeric',
  }).toUpperCase();

  return (
    <div
      className={dark ? 'hw-hardware-pressroom-bench' : undefined}
      style={{
        position: 'relative',
        flex: 1,
        padding: '32px 32px 96px 32px',
        background: dark ? undefined : 'transparent',
        transition: 'background-color 0.5s cubic-bezier(0.4,0,0.2,1)',
        overflow: 'hidden',
        minHeight: 0,
      }}
    >
      {/* DRAWING SHEET */}
      <div style={{
        position: 'relative',
        width: '100%',
        height: '100%',
        background: sheetBg,
        border: `1px solid ${sheetBorder}`,
        boxShadow: dark
          ? '0 0 0 1px rgba(192,57,43,0.06), 0 24px 60px rgba(0,0,0,0.6)'
          : '0 1px 0 rgba(0,0,0,0.03), 0 18px 48px rgba(60,40,20,0.10)',
        transition: 'all 0.5s cubic-bezier(0.4,0,0.2,1)',
        overflow: 'hidden',
      }}>
        <DrawingSheetMathGrid dark={dark} />

        {/* REGISTRATION MARKS */}
        {(['tl','tr','bl','br'] as const).map(pos => (
          <div key={pos} style={{
            position: 'absolute',
            width: 22, height: 22,
            top:    pos.startsWith('t') ? 18 : undefined,
            bottom: pos.startsWith('b') ? 18 : undefined,
            left:   pos.endsWith('l')   ? 18 : undefined,
            right:  pos.endsWith('r')   ? 18 : undefined,
            borderTop:    pos.startsWith('t') ? `1px solid ${regCol}` : undefined,
            borderBottom: pos.startsWith('b') ? `1px solid ${regCol}` : undefined,
            borderLeft:   pos.endsWith('l')   ? `1px solid ${regCol}` : undefined,
            borderRight:  pos.endsWith('r')   ? `1px solid ${regCol}` : undefined,
            transition: 'border-color 0.5s ease',
          }} />
        ))}

        {/* TOP RAIL — STANDING TYPE */}
        <div style={{
          position: 'absolute',
          top: 22,
          left: '50%',
          transform: 'translateX(-50%)',
          fontFamily: "'Courier New', monospace",
          fontSize: 10,
          letterSpacing: '0.3em',
          color: RED,
          whiteSpace: 'nowrap',
          pointerEvents: 'none',
          fontWeight: 500,
        }}>
          STANDING TYPE · HARDWARE ATELIER
        </div>

        {/* PRESSROOM TOGGLE — LARGE */}
        <button
          onClick={() => setDark(d => !d)}
          style={{
            position: 'absolute',
            top: 18,
            right: 22,
            background: dark ? '#1a1a1a' : 'transparent',
            border: `0.5px solid ${dark ? '#444' : '#1a1a1a'}`,
            padding: '8px 14px',
            cursor: 'pointer',
            fontFamily: "'Courier New', monospace",
            fontSize: 9,
            letterSpacing: '0.18em',
            color: dark ? '#e8e4dc' : '#1a1a1a',
            display: 'flex',
            alignItems: 'center',
            gap: 8,
            transition: 'all 0.25s ease',
            zIndex: 20,
          }}
          onMouseEnter={(e) => {
            e.currentTarget.style.background = dark ? '#222' : '#1a1a1a';
            e.currentTarget.style.color = dark ? '#fff' : '#f5f0e8';
          }}
          onMouseLeave={(e) => {
            e.currentTarget.style.background = dark ? '#1a1a1a' : 'transparent';
            e.currentTarget.style.color = dark ? '#e8e4dc' : '#1a1a1a';
          }}
        >
          <span style={{
            display: 'inline-block',
            width: 8, height: 8,
            borderRadius: '50%',
            background: dark ? '#f5f0e8' : '#1a1a1a',
            transition: 'background 0.3s ease',
          }} />
          {dark ? 'DAYLIGHT' : 'PRESSROOM'}
        </button>

        {/* MAIN STAGE */}
        <EmptyHologram dark={dark} rotation={rotation} subtleText={subtleText} valCol={valCol} />

        {/* TITLE BLOCK — BOTTOM RIGHT */}
        <div style={{
          position: 'absolute',
          bottom: 28,
          right: 28,
          minWidth: 280,
          background: dark ? 'rgba(15,15,15,0.92)' : 'rgba(245,240,232,0.94)',
          border: `0.5px solid ${dark ? '#333' : '#1a1a1a'}`,
          padding: '14px 18px',
          backdropFilter: 'blur(2px)',
          transition: 'all 0.5s ease',
        }}>
          <div style={{
            fontFamily: "'Courier New', monospace",
            fontSize: 9,
            letterSpacing: '0.22em',
            color: RED,
            paddingBottom: 8,
            marginBottom: 10,
            borderBottom: `0.5px solid ${dark ? '#2a2a2a' : '#c4bfb4'}`,
          }}>
            ENGINEERING TITLE BLOCK
          </div>
          {[
            ['PROJECT',  productName],
            ['CATEGORY', category],
          ].map(([l, v]) => (
            <TitleRow key={l} label={l} value={v} lblCol={lblCol} valCol={valCol} />
          ))}
          <Divider dark={dark} />
          {[
            ['COMPONENTS', '—'],
            ['EST. MASS',  '—'],
            ['SCALE',      '—'],
          ].map(([l, v]) => (
            <TitleRow key={l} label={l} value={v} lblCol={lblCol} valCol={valCol} />
          ))}
          <Divider dark={dark} />
          {[
            ['EDITION', 'HARDWARE ATELIER'],
            ['FILED',   hasSpec ? today : 'PENDING PRESS'],
          ].map(([l, v]) => (
            <TitleRow key={l} label={l} value={v} lblCol={lblCol} valCol={valCol} />
          ))}
        </div>
      </div>

      {/* ACTION BAR — BOTTOM */}
      <div style={{
        position: 'absolute',
        bottom: 24,
        left: 32,
        right: 32,
        height: 56,
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'space-between',
        gap: 16,
        zIndex: 5,
      }}>
        <ActionButton onClick={onBack} dark={dark}>
          ← BACK TO DOSSIER
        </ActionButton>

        <div style={{
          display: 'flex',
          border: `0.5px solid ${dark ? '#333' : '#1a1a1a'}`,
          background: dark ? '#0f0f0f' : 'rgba(255,255,255,0.35)',
          transition: 'all 0.5s ease',
        }}>
          <ToggleSeg active={true}  dark={dark}>BLUEPRINT</ToggleSeg>
          <ToggleSeg active={false} dark={dark}>DIAGRAM</ToggleSeg>
        </div>

        <PrimaryButton
          onClick={onRunPhysics}
          disabled={!hasSpec}
          dark={dark}
        >
          RUN PHYSICS →
        </PrimaryButton>
      </div>
    </div>
  );
}

function DrawingSheetMathGrid({ dark }: { dark: boolean }) {
  const line = dark ? 'rgba(255,255,255,0.07)' : 'rgba(26,23,20,0.1)';
  const s = DRAWING_SHEET_GRID_STEP_PX;
  return (
    <div
      aria-hidden
      style={{
        position: 'absolute',
        inset: 0,
        zIndex: 0,
        backgroundImage: `
          linear-gradient(${line} 1px, transparent 1px),
          linear-gradient(90deg, ${line} 1px, transparent 1px)
        `,
        backgroundSize: `${s}px ${s}px`,
        pointerEvents: 'none',
      }}
    />
  );
}

// ────────── EMPTY HOLOGRAM ──────────

function EmptyHologram({
  dark, rotation, subtleText, valCol,
}: {
  dark: boolean;
  rotation: number;
  subtleText: string;
  valCol: string;
}) {
  const stroke = dark ? '#c0392b' : '#1a1a1a';
  const accent = '#c0392b';
  const glow   = dark
    ? 'drop-shadow(0 0 24px rgba(192,57,43,0.35))'
    : 'drop-shadow(0 4px 12px rgba(0,0,0,0.08))';

  return (
    <div style={{
      position: 'absolute',
      top: '50%',
      left: '50%',
      transform: 'translate(-50%, -54%)',
      textAlign: 'center',
      pointerEvents: 'none',
    }}>
      <div style={{
        position: 'relative',
        width: 380,
        height: 380,
        margin: '0 auto',
        filter: glow,
      }}>
        {/* OUTER RING — STATIC */}
        <svg width={380} height={380} viewBox="0 0 380 380"
             style={{ position: 'absolute', inset: 0 }}>
          <circle cx={190} cy={190} r={184}
            fill="none" stroke={stroke}
            strokeWidth={0.5} strokeDasharray="2 6"
            opacity={dark ? 0.4 : 0.25} />
          <circle cx={190} cy={190} r={150}
            fill="none" stroke={stroke}
            strokeWidth={0.5}
            opacity={dark ? 0.3 : 0.18} />
          {[0, 90, 180, 270].map(a => (
            <line key={a}
              x1={190 + 184 * Math.cos((a - 90) * Math.PI / 180)}
              y1={190 + 184 * Math.sin((a - 90) * Math.PI / 180)}
              x2={190 + 196 * Math.cos((a - 90) * Math.PI / 180)}
              y2={190 + 196 * Math.sin((a - 90) * Math.PI / 180)}
              stroke={accent} strokeWidth={1} />
          ))}
          {[0, 30, 60, 120, 150, 210, 240, 300, 330].map(a => (
            <line key={a}
              x1={190 + 184 * Math.cos((a - 90) * Math.PI / 180)}
              y1={190 + 184 * Math.sin((a - 90) * Math.PI / 180)}
              x2={190 + 190 * Math.cos((a - 90) * Math.PI / 180)}
              y2={190 + 190 * Math.sin((a - 90) * Math.PI / 180)}
              stroke={stroke} strokeWidth={0.5}
              opacity={dark ? 0.4 : 0.3} />
          ))}
        </svg>

        {/* ROTATING WIREFRAME ICOSAHEDRON */}
        <svg
          width={380} height={380} viewBox="0 0 380 380"
          style={{
            position: 'absolute',
            inset: 0,
            transform: `rotate(${rotation}deg)`,
          }}
        >
          <g transform="translate(190 190)">
            <Icosahedron stroke={stroke} accent={accent} />
          </g>
        </svg>

        {/* CROSSHAIR */}
        <svg width={380} height={380} viewBox="0 0 380 380"
             style={{ position: 'absolute', inset: 0 }}>
          <line x1={190} y1={60}  x2={190} y2={100} stroke={accent} strokeWidth={0.8} />
          <line x1={190} y1={280} x2={190} y2={320} stroke={accent} strokeWidth={0.8} />
          <line x1={60}  y1={190} x2={100} y2={190} stroke={accent} strokeWidth={0.8} />
          <line x1={280} y1={190} x2={320} y2={190} stroke={accent} strokeWidth={0.8} />
          <circle cx={190} cy={190} r={3} fill={accent} />
        </svg>
      </div>

      {/* CALL TO ACTION */}
      <div style={{ marginTop: 32 }}>
        <div style={{
          fontFamily: "'Courier New', monospace",
          fontSize: 11,
          letterSpacing: '0.32em',
          color: accent,
          marginBottom: 14,
          fontWeight: 500,
        }}>
          AWAITING SPECIFICATION
        </div>
        <div style={{
          fontFamily: 'Georgia, serif',
          fontStyle: 'italic',
          fontSize: 18,
          color: valCol,
          letterSpacing: '-0.01em',
          maxWidth: 360,
          margin: '0 auto',
          lineHeight: 1.4,
          transition: 'color 0.5s ease',
        }}>
          File the build sheet on the left. The bench will press a solid you can rotate, measure, and interrogate.
        </div>
        <div style={{
          fontFamily: "'Courier New', monospace",
          fontSize: 9,
          letterSpacing: '0.18em',
          color: subtleText,
          marginTop: 18,
          transition: 'color 0.5s ease',
        }}>
          NO PLATE FILED · STANDING BY
        </div>
      </div>
    </div>
  );
}

function Icosahedron({ stroke, accent }: {
  stroke: string; accent: string;
}) {
  const t = (1 + Math.sqrt(5)) / 2;
  const r = 90;
  const verts3d: [number, number, number][] = [
    [-1,  t,  0], [ 1,  t,  0], [-1, -t,  0], [ 1, -t,  0],
    [ 0, -1,  t], [ 0,  1,  t], [ 0, -1, -t], [ 0,  1, -t],
    [ t,  0, -1], [ t,  0,  1], [-t,  0, -1], [-t,  0,  1],
  ];
  const project = ([x, y, z]: [number, number, number]) => {
    const f = 1 / (3 - z * 0.18);
    return [x * r * f, y * r * f] as [number, number];
  };
  const v = verts3d.map(project);
  const edges: [number, number][] = [
    [0,1],[0,5],[0,7],[0,10],[0,11],[1,5],[1,7],[1,8],[1,9],
    [2,3],[2,4],[2,6],[2,10],[2,11],[3,4],[3,6],[3,8],[3,9],
    [4,5],[4,9],[4,11],[5,9],[5,11],[6,7],[6,8],[6,10],
    [7,8],[7,10],[8,9],[10,11],
  ];
  return (
    <g>
      {edges.map(([a, b], i) => (
        <line key={i}
          x1={v[a][0]} y1={v[a][1]}
          x2={v[b][0]} y2={v[b][1]}
          stroke={stroke}
          strokeWidth={0.8}
          opacity={0.55}
        />
      ))}
      {v.map(([x, y], i) => (
        <circle key={i} cx={x} cy={y} r={2}
          fill={accent} />
      ))}
    </g>
  );
}

// ────────── SHARED SUB-COMPONENTS ──────────

function TitleRow({
  label, value, lblCol, valCol,
}: {
  label: string; value: string;
  lblCol: string; valCol: string;
}) {
  return (
    <div style={{
      display: 'flex',
      justifyContent: 'space-between',
      gap: 24,
      marginBottom: 4,
    }}>
      <span style={{
        fontFamily: "'Courier New', monospace",
        fontSize: 9, letterSpacing: '0.14em',
        color: lblCol,
        transition: 'color 0.5s ease',
      }}>{label}</span>
      <span style={{
        fontFamily: "'Courier New', monospace",
        fontSize: 9, color: valCol, textAlign: 'right',
        transition: 'color 0.5s ease',
      }}>{value}</span>
    </div>
  );
}

function Divider({ dark }: { dark: boolean }) {
  return (
    <hr style={{
      border: 'none',
      borderTop: `0.5px solid ${dark ? '#2a2a2a' : '#c4bfb4'}`,
      margin: '8px 0',
      transition: 'border-color 0.5s ease',
    }} />
  );
}

function ActionButton({
  onClick, dark, children,
}: {
  onClick?: () => void; dark: boolean; children: React.ReactNode;
}) {
  return (
    <button onClick={onClick} style={{
      background: 'transparent',
      border: `0.5px solid ${dark ? '#444' : '#1a1a1a'}`,
      padding: '12px 20px',
      fontFamily: "'Courier New', monospace",
      fontSize: 11,
      letterSpacing: '0.18em',
      color: dark ? '#e8e4dc' : '#1a1a1a',
      cursor: 'pointer',
      transition: 'all 0.2s ease',
    }}
    onMouseEnter={(e) => {
      e.currentTarget.style.background = dark ? '#1a1a1a' : '#1a1a1a';
      e.currentTarget.style.color = '#f5f0e8';
    }}
    onMouseLeave={(e) => {
      e.currentTarget.style.background = 'transparent';
      e.currentTarget.style.color = dark ? '#e8e4dc' : '#1a1a1a';
    }}>
      {children}
    </button>
  );
}

function ToggleSeg({
  active, dark, children,
}: {
  active: boolean; dark: boolean; children: React.ReactNode;
}) {
  return (
    <button style={{
      background: active ? '#1a1a1a' : 'transparent',
      color: active ? '#f5f0e8' : (dark ? '#888' : '#1a1a1a'),
      padding: '12px 22px',
      border: 'none',
      borderLeft: active ? 'none' : `0.5px solid ${dark ? '#333' : '#1a1a1a'}`,
      fontFamily: "'Courier New', monospace",
      fontSize: 11,
      letterSpacing: '0.18em',
      cursor: 'pointer',
      transition: 'all 0.2s ease',
    }}>
      {children}
    </button>
  );
}

function PrimaryButton({
  onClick, disabled, dark, children,
}: {
  onClick?: () => void; disabled: boolean; dark: boolean; children: React.ReactNode;
}) {
  const enabled = !disabled;
  return (
    <button
      onClick={onClick}
      disabled={disabled}
      style={{
        background: enabled ? '#c0392b' : (dark ? '#1a1a1a' : '#bbb'),
        color: '#f5f0e8',
        border: enabled ? '0.5px solid #c0392b' : `0.5px solid ${dark ? '#333' : '#999'}`,
        padding: '14px 26px',
        fontFamily: "'Courier New', monospace",
        fontSize: 11,
        letterSpacing: '0.2em',
        cursor: enabled ? 'pointer' : 'not-allowed',
        transition: 'all 0.2s ease',
        opacity: enabled ? 1 : 0.7,
        fontWeight: 500,
      }}
      onMouseEnter={(e) => {
        if (enabled) e.currentTarget.style.background = '#a82c1f';
      }}
      onMouseLeave={(e) => {
        if (enabled) e.currentTarget.style.background = '#c0392b';
      }}
    >
      {children}
    </button>
  );
}
