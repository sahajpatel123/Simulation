'use client'

/* ════════════════════════════════════════════════════════════════════
 *  TheCee — "The Observatory"
 *  A cinematic, living landing page.
 *  Your idea, thrown under a million synthetic markets, in real time.
 * ════════════════════════════════════════════════════════════════════ */

import { useEffect, useMemo, useRef, useState, type CSSProperties } from 'react'
import { motion, useScroll, useTransform, useSpring, AnimatePresence } from 'framer-motion'
import Link from 'next/link'
import { ArrowRight, ArrowUpRight, Play, Sparkles, Check, Radio } from 'lucide-react'

import InlineAuth from '@/components/landing/InlineAuth'
import { useAuthStore } from '@/store/auth.store'
import { auth as authLib } from '@/lib/auth'
import { useLogout } from '@/hooks/useAuth'

/* ──────────────────────────────────────────────────────────────────
 *  Theme tokens (scoped by inline styles to avoid colliding with the
 *  editorial theme used by the rest of the app).
 * ────────────────────────────────────────────────────────────────── */
const T = {
  void: '#06060a',
  voidRaised: '#0d0d14',
  voidPanel: '#13131c',
  voidPanelHi: '#1b1b26',
  edge: 'rgba(255,255,255,0.08)',
  edgeHi: 'rgba(255,255,255,0.16)',
  text: '#f3eee4',
  textDim: 'rgba(243,238,228,0.62)',
  textFaint: 'rgba(243,238,228,0.34)',
  ember: '#ff6a3d',
  emberSoft: 'rgba(255,106,61,0.14)',
  gold: '#e5b667',
  jade: '#7fffa6',
  dim: '#ff5e5e',
  serif: "var(--font-serif, 'Playfair Display', Georgia, serif)",
  mono: "ui-monospace, 'SF Mono', Menlo, monospace",
} as const

/* ───── Copy ─────────────────────────────────────────────────────── */
const QUESTIONS = [
  'actually work?',
  'actually sell?',
  'actually scale?',
  'survive year one?',
  'earn its price?',
  'find its people?',
  'outlast the noise?',
] as const

const INSTRUMENTS = [
  {
    tag: 'I · Capture',
    title: 'Your idea, in your words',
    body:
      'No frameworks, no lean canvases. Type it the way you would pitch it to a friend at midnight. Our architects extract the assumptions you did not know you were making.',
    stat: '~18s',
    statLabel: 'to parse an idea',
  },
  {
    tag: 'II · Populate',
    title: 'A million synthetic markets',
    body:
      'Architects assemble cohorts: buyers, skeptics, switchers, lurkers, repeaters, the bored. Every one carries a weighted belief about price, channel, and trust. They do not flatter you.',
    stat: '10⁶',
    statLabel: 'agents in play',
  },
  {
    tag: 'III · Report',
    title: 'The autopsy, before the burial',
    body:
      'Failure modes ranked. Surviving paths drawn. The specific interventions that shift the distribution, ordered by the odds they move. Filed, dated, stamped — on your desk in under two minutes.',
    stat: '≤ 120s',
    statLabel: 'to a full dossier',
  },
] as const

const VOICES = [
  {
    bar: 'First issue · zero cost',
    title: 'I killed the idea before I quit my job.',
    body:
      'Three runs told me the channel I was betting on was already dead. Saved myself eight months and a line of credit.',
    sig: 'Field · Bangalore',
    role: 'First-time founder',
  },
  {
    bar: 'Pricing on the line',
    title: 'We raised the price, not the volume.',
    body:
      'The simulation said raising by 40% kept 71% of the willingness. We shipped it on Monday. It held.',
    sig: 'Studio · Pune',
    role: 'Product lead',
  },
  {
    bar: 'D2C / physical',
    title: 'The pallet was two weeks from shipping.',
    body:
      'Two thousand readers later, the reorder rate was a third of what the deck claimed. We pulled the order. That was the whole point.',
    sig: 'Workshop · Surat',
    role: 'Brand founder',
  },
  {
    bar: 'Nights & weekends',
    title: 'Permission to keep building.',
    body:
      'I ran six ideas through on a Sunday. Five died. The sixth earned my evenings for the next year.',
    sig: 'Desk · Hyderabad',
    role: 'Weekend builder',
  },
] as const

const TIERS = [
  {
    name: 'Single Issue',
    kicker: 'For your first dossier',
    price: '₹0',
    sub: 'Free, forever',
    bullets: ['1 active dossier', '500 synthetic readers', 'Full pre-mortem report', 'Filed in under 2 min'],
    cta: 'Open the observatory',
    glow: false,
  },
  {
    name: 'Quarterly',
    kicker: 'For working founders',
    price: '₹1,200',
    sub: 'per month',
    bullets: ['10 active dossiers', '10,000 readers per run', 'Decision Studio', 'Cross-validation 3×', 'Priority queue'],
    cta: 'Subscribe quarterly',
    glow: true,
  },
  {
    name: 'Press Pass',
    kicker: 'For studios & funds',
    price: 'Talk',
    sub: 'with the editor',
    bullets: ['Unlimited dossiers', 'Custom cohort design', 'Team collaborators', 'API & data exports', 'Named architect'],
    cta: 'Request a press pass',
    glow: false,
  },
] as const

const DISTRIBUTION = [
  { label: 'Dies fast', pct: 14, tint: T.dim, note: 'runway gone inside 90 days' },
  { label: 'Quiet death', pct: 23, tint: '#c87b3a', note: 'grows, then stalls without recovering' },
  { label: 'Pivots', pct: 31, tint: T.gold, note: 'the idea survives; the shape changes' },
  { label: 'Survives', pct: 22, tint: '#9ecf7e', note: 'modest, durable, compounding' },
  { label: 'Scales', pct: 10, tint: T.jade, note: 'the distribution you are betting on' },
] as const

/* ═════════════════════════════════════════════════════════════════
 *  Cursor halo — a warm spotlight following the cursor, only on dark.
 * ═════════════════════════════════════════════════════════════════ */
function CursorHalo() {
  const x = useSpring(0, { stiffness: 120, damping: 20, mass: 0.4 })
  const y = useSpring(0, { stiffness: 120, damping: 20, mass: 0.4 })

  useEffect(() => {
    const move = (e: MouseEvent) => {
      x.set(e.clientX)
      y.set(e.clientY)
    }
    window.addEventListener('mousemove', move)
    return () => window.removeEventListener('mousemove', move)
  }, [x, y])

  return (
    <motion.div
      aria-hidden
      style={{
        position: 'fixed',
        top: 0,
        left: 0,
        width: 480,
        height: 480,
        translateX: x,
        translateY: y,
        x: '-50%',
        y: '-50%',
        pointerEvents: 'none',
        zIndex: 5,
        background:
          'radial-gradient(circle at center, rgba(255,106,61,0.14) 0%, rgba(255,106,61,0.05) 28%, transparent 62%)',
        mixBlendMode: 'screen',
      }}
    />
  )
}

/* ═════════════════════════════════════════════════════════════════
 *  Particle field — the living observatory behind the hero.
 *  800 drifting agents, magnetized to cursor, clustering on demand.
 * ═════════════════════════════════════════════════════════════════ */
type FieldMode = 'drift' | 'cluster' | 'shatter'

function ObservatoryField({ mode, trigger }: { mode: FieldMode; trigger: number }) {
  const canvasRef = useRef<HTMLCanvasElement>(null)
  const modeRef = useRef(mode)
  useEffect(() => {
    modeRef.current = mode
  }, [mode])

  useEffect(() => {
    const canvas = canvasRef.current
    if (!canvas) return
    const ctx = canvas.getContext('2d')
    if (!ctx) return

    const dpr = Math.min(window.devicePixelRatio || 1, 1.75)
    let w = 0
    let h = 0
    const resize = () => {
      const parent = canvas.parentElement
      w = parent?.clientWidth || window.innerWidth
      h = parent?.clientHeight || window.innerHeight
      canvas.width = Math.floor(w * dpr)
      canvas.height = Math.floor(h * dpr)
      canvas.style.width = w + 'px'
      canvas.style.height = h + 'px'
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0)
    }
    resize()
    window.addEventListener('resize', resize)

    const isMobile = window.innerWidth < 700
    const N = isMobile ? 220 : 640

    type P = {
      x: number; y: number
      vx: number; vy: number
      r: number
      base: number           // base luminance 0..1
      hueShift: number       // -1..1 (ember→jade bias)
      ox: number; oy: number // original anchor
    }

    const particles: P[] = []
    for (let i = 0; i < N; i++) {
      const x = Math.random() * w
      const y = Math.random() * h
      particles.push({
        x, y,
        vx: (Math.random() - 0.5) * 0.25,
        vy: (Math.random() - 0.5) * 0.25,
        r: 0.6 + Math.random() * 1.9,
        base: 0.2 + Math.random() * 0.8,
        hueShift: Math.random() * 2 - 1,
        ox: x, oy: y,
      })
    }

    const mouse = { x: -9999, y: -9999, inside: false }
    const onMove = (e: MouseEvent) => {
      const r = canvas.getBoundingClientRect()
      mouse.x = e.clientX - r.left
      mouse.y = e.clientY - r.top
      mouse.inside = mouse.x >= 0 && mouse.x <= w && mouse.y >= 0 && mouse.y <= h
    }
    const onLeave = () => { mouse.inside = false; mouse.x = -9999; mouse.y = -9999 }
    window.addEventListener('mousemove', onMove)
    window.addEventListener('mouseleave', onLeave)

    let raf = 0
    let t = 0
    let impulse = 0

    const loop = () => {
      t += 0.016
      if (impulse > 0) impulse -= 0.02
      const cx = w / 2
      const cy = h / 2

      // soft trail — don't fully clear, leave ghost
      ctx.fillStyle = 'rgba(6,6,10,0.22)'
      ctx.fillRect(0, 0, w, h)

      const m = modeRef.current

      for (let i = 0; i < particles.length; i++) {
        const p = particles[i]

        // drift field — slow lissajous flow
        const flowX = Math.sin((p.y + t * 20) * 0.0045) * 0.06
        const flowY = Math.cos((p.x + t * 18) * 0.0045) * 0.06
        p.vx += flowX
        p.vy += flowY

        // mode behaviour
        if (m === 'cluster') {
          // pull toward three attractor points arranged as a triangle
          const tx = [cx - w * 0.18, cx + w * 0.18, cx][i % 3]
          const ty = [cy + h * 0.08, cy + h * 0.08, cy - h * 0.14][i % 3]
          const dx = tx - p.x
          const dy = ty - p.y
          p.vx += dx * 0.0018
          p.vy += dy * 0.0018
        } else if (m === 'shatter') {
          // radial explosion from center
          const dx = p.x - cx
          const dy = p.y - cy
          const d = Math.hypot(dx, dy) || 1
          p.vx += (dx / d) * 0.12 * impulse
          p.vy += (dy / d) * 0.12 * impulse
        }

        // cursor magnetism (subtle attraction)
        if (mouse.inside) {
          const dx = mouse.x - p.x
          const dy = mouse.y - p.y
          const d2 = dx * dx + dy * dy
          if (d2 < 160 * 160) {
            const d = Math.sqrt(d2) || 1
            const f = (1 - d / 160) * 0.18
            p.vx += (dx / d) * f
            p.vy += (dy / d) * f
          }
        }

        // damp
        p.vx *= 0.94
        p.vy *= 0.94
        p.x += p.vx
        p.y += p.vy

        // wrap
        if (p.x < -10) p.x = w + 10
        if (p.x > w + 10) p.x = -10
        if (p.y < -10) p.y = h + 10
        if (p.y > h + 10) p.y = -10

        // colour — ember on the warm half, pale cream on the cool half
        const warm = p.hueShift > 0
        const alpha = 0.18 + 0.75 * p.base * (0.55 + 0.45 * Math.sin(t * 1.2 + i * 0.3))
        const col = warm
          ? `rgba(255, ${Math.floor(150 - p.base * 60)}, ${Math.floor(90 - p.base * 40)}, ${alpha})`
          : `rgba(243, 238, 228, ${alpha * 0.55})`

        ctx.beginPath()
        ctx.arc(p.x, p.y, p.r, 0, Math.PI * 2)
        ctx.fillStyle = col
        ctx.fill()
      }

      // thin connecting threads for nearby particles (low cost: only sample a subset)
      ctx.lineWidth = 0.4
      const SAMPLE = isMobile ? 60 : 140
      for (let i = 0; i < SAMPLE; i++) {
        const a = particles[(i * 7) % particles.length]
        const b = particles[(i * 13 + 5) % particles.length]
        const dx = a.x - b.x
        const dy = a.y - b.y
        const d2 = dx * dx + dy * dy
        if (d2 < 90 * 90) {
          const alpha = (1 - Math.sqrt(d2) / 90) * 0.08
          ctx.strokeStyle = `rgba(243,238,228,${alpha})`
          ctx.beginPath()
          ctx.moveTo(a.x, a.y)
          ctx.lineTo(b.x, b.y)
          ctx.stroke()
        }
      }

      raf = requestAnimationFrame(loop)
    }
    loop()

    return () => {
      cancelAnimationFrame(raf)
      window.removeEventListener('resize', resize)
      window.removeEventListener('mousemove', onMove)
      window.removeEventListener('mouseleave', onLeave)
    }
  }, [])

  // `trigger` changes cause a re-render which the loop's closure doesn't need;
  // the visible effect comes from `mode` flipping to 'cluster' via modeRef.
  void trigger

  return (
    <canvas
      ref={canvasRef}
      style={{
        position: 'absolute',
        inset: 0,
        width: '100%',
        height: '100%',
        pointerEvents: 'none',
        zIndex: 0,
      }}
      aria-hidden
    />
  )
}

/* ═════════════════════════════════════════════════════════════════
 *  Cycling question — headline that swaps its last clause.
 * ═════════════════════════════════════════════════════════════════ */
function CyclingQuestion() {
  const [i, setI] = useState(0)
  useEffect(() => {
    const t = setInterval(() => setI(p => (p + 1) % QUESTIONS.length), 2600)
    return () => clearInterval(t)
  }, [])
  return (
    <span style={{ position: 'relative', display: 'inline-block', minWidth: 'min(620px, 92vw)' }}>
      <AnimatePresence mode="wait">
        <motion.span
          key={QUESTIONS[i]}
          initial={{ y: 28, opacity: 0, filter: 'blur(8px)' }}
          animate={{ y: 0, opacity: 1, filter: 'blur(0px)' }}
          exit={{ y: -24, opacity: 0, filter: 'blur(6px)' }}
          transition={{ duration: 0.55, ease: [0.22, 0.8, 0.2, 1] }}
          style={{
            display: 'inline-block',
            fontStyle: 'italic',
            color: T.ember,
            textShadow: '0 0 36px rgba(255,106,61,0.18)',
          }}
        >
          {QUESTIONS[i]}
        </motion.span>
      </AnimatePresence>
    </span>
  )
}

/* ═════════════════════════════════════════════════════════════════
 *  Top nav — fixed, translucent, minimalist.
 * ═════════════════════════════════════════════════════════════════ */
function TopBar({
  isAuthed,
  isHydrated,
  onSignIn,
  onSignUp,
  onLogout,
  userEmail,
}: {
  isAuthed: boolean
  isHydrated: boolean
  onSignIn: () => void
  onSignUp: () => void
  onLogout: () => void
  userEmail?: string
}) {
  const [scrolled, setScrolled] = useState(false)
  useEffect(() => {
    const onScroll = () => setScrolled(window.scrollY > 30)
    onScroll()
    window.addEventListener('scroll', onScroll, { passive: true })
    return () => window.removeEventListener('scroll', onScroll)
  }, [])

  return (
    <motion.header
      initial={{ y: -30, opacity: 0 }}
      animate={{ y: 0, opacity: 1 }}
      transition={{ duration: 0.7, ease: [0.2, 0.8, 0.2, 1] }}
      style={{
        position: 'fixed',
        top: 0,
        left: 0,
        right: 0,
        zIndex: 60,
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'space-between',
        padding: scrolled ? '14px 32px' : '22px 40px',
        background: scrolled ? 'rgba(6,6,10,0.72)' : 'transparent',
        backdropFilter: scrolled ? 'blur(14px) saturate(1.1)' : 'none',
        WebkitBackdropFilter: scrolled ? 'blur(14px) saturate(1.1)' : 'none',
        borderBottom: scrolled ? `0.5px solid ${T.edge}` : '0.5px solid transparent',
        transition: 'padding 280ms ease, background 280ms ease, border-color 280ms ease',
      }}
    >
      {/* left — wordmark */}
      <Link href="/" style={{ textDecoration: 'none', display: 'flex', alignItems: 'baseline', gap: 12 }}>
        <span
          style={{
            fontFamily: T.serif,
            fontWeight: 900,
            fontStyle: 'italic',
            fontSize: 26,
            color: T.text,
            letterSpacing: '-0.035em',
            lineHeight: 1,
          }}
        >
          TheCee
        </span>
        <span
          style={{
            fontFamily: T.mono,
            fontSize: 9,
            letterSpacing: '0.22em',
            color: T.textFaint,
            textTransform: 'uppercase',
          }}
        >
          The Observatory
        </span>
      </Link>

      {/* center — live pulse */}
      <div
        style={{
          position: 'absolute',
          left: '50%',
          transform: 'translateX(-50%)',
          display: 'flex',
          alignItems: 'center',
          gap: 10,
          fontFamily: T.mono,
          fontSize: 10,
          letterSpacing: '0.2em',
          textTransform: 'uppercase',
          color: T.textDim,
        }}
      >
        <motion.span
          style={{
            width: 6,
            height: 6,
            borderRadius: 999,
            background: T.ember,
            boxShadow: `0 0 14px ${T.ember}`,
          }}
          animate={{ opacity: [1, 0.25, 1] }}
          transition={{ duration: 1.6, repeat: Infinity, ease: 'easeInOut' }}
        />
        Live · {new Date().toLocaleDateString('en-GB', { month: 'short', year: 'numeric' })}
      </div>

      {/* right — auth */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 22 }}>
        {isHydrated && isAuthed ? (
          <>
            <span
              style={{
                fontFamily: T.mono,
                fontSize: 10,
                letterSpacing: '0.18em',
                textTransform: 'uppercase',
                color: T.textFaint,
                maxWidth: 160,
                overflow: 'hidden',
                textOverflow: 'ellipsis',
                whiteSpace: 'nowrap',
              }}
            >
              {userEmail}
            </span>
            <button
              type="button"
              onClick={onLogout}
              style={{
                background: 'transparent',
                border: `0.5px solid ${T.edge}`,
                color: T.textDim,
                padding: '7px 14px',
                fontFamily: T.mono,
                fontSize: 10,
                letterSpacing: '0.18em',
                textTransform: 'uppercase',
                cursor: 'pointer',
              }}
              onMouseEnter={e => { e.currentTarget.style.color = T.text; e.currentTarget.style.borderColor = T.edgeHi }}
              onMouseLeave={e => { e.currentTarget.style.color = T.textDim; e.currentTarget.style.borderColor = T.edge }}
            >
              Sign out
            </button>
            <Link
              href="/projects"
              style={{
                display: 'inline-flex',
                alignItems: 'center',
                gap: 8,
                background: T.ember,
                color: T.void,
                padding: '9px 18px',
                fontFamily: T.mono,
                fontSize: 10,
                letterSpacing: '0.2em',
                textTransform: 'uppercase',
                fontWeight: 600,
                textDecoration: 'none',
                boxShadow: `0 8px 28px ${T.emberSoft}`,
              }}
            >
              Enter observatory <ArrowRight size={12} />
            </Link>
          </>
        ) : isHydrated ? (
          <>
            <button
              type="button"
              onClick={onSignIn}
              style={{
                background: 'transparent',
                border: 'none',
                color: T.textDim,
                fontFamily: T.mono,
                fontSize: 10,
                letterSpacing: '0.2em',
                textTransform: 'uppercase',
                cursor: 'pointer',
              }}
              onMouseEnter={e => (e.currentTarget.style.color = T.text)}
              onMouseLeave={e => (e.currentTarget.style.color = T.textDim)}
            >
              Sign in
            </button>
            <button
              type="button"
              onClick={onSignUp}
              style={{
                display: 'inline-flex',
                alignItems: 'center',
                gap: 8,
                background: T.text,
                color: T.void,
                padding: '9px 18px',
                fontFamily: T.mono,
                fontSize: 10,
                letterSpacing: '0.2em',
                textTransform: 'uppercase',
                fontWeight: 600,
                border: 'none',
                cursor: 'pointer',
              }}
            >
              Open access <ArrowRight size={12} />
            </button>
          </>
        ) : null}
      </div>
    </motion.header>
  )
}

/* ═════════════════════════════════════════════════════════════════
 *  Thin top scroll progress bar (ember)
 * ═════════════════════════════════════════════════════════════════ */
function ScrollProgress() {
  const { scrollYProgress } = useScroll()
  const w = useTransform(scrollYProgress, v => `${v * 100}%`)
  return (
    <motion.div
      aria-hidden
      style={{
        position: 'fixed',
        top: 0,
        left: 0,
        height: 2,
        width: w,
        background: `linear-gradient(90deg, ${T.ember}, ${T.gold})`,
        zIndex: 90,
        boxShadow: `0 0 10px ${T.ember}`,
      }}
    />
  )
}

/* ═════════════════════════════════════════════════════════════════
 *  Reveal helper
 * ═════════════════════════════════════════════════════════════════ */
function Reveal({ children, delay = 0, y = 24, className, style }: {
  children: React.ReactNode; delay?: number; y?: number; className?: string; style?: CSSProperties
}) {
  return (
    <motion.div
      initial={{ opacity: 0, y }}
      whileInView={{ opacity: 1, y: 0 }}
      viewport={{ once: true, margin: '-40px' }}
      transition={{ duration: 0.75, delay, ease: [0.2, 0.7, 0.2, 1] }}
      className={className}
      style={style}
    >
      {children}
    </motion.div>
  )
}

/* ═════════════════════════════════════════════════════════════════
 *  Live ticker of scenarios (numbers rolling, like a press counter
 *  turned into a trading ticker). Deterministic seeds, no randomness
 *  issues on hydration since we only start ticking after mount.
 * ═════════════════════════════════════════════════════════════════ */
function RunningTicker() {
  const [scenarios, setScenarios] = useState(1_420_812)
  const [dossiers, setDossiers] = useState(87)
  const [observers, setObservers] = useState(23)
  const [runs, setRuns] = useState(4)

  useEffect(() => {
    const a = setInterval(() => setScenarios(s => s + 2 + Math.floor(Math.random() * 11)), 260)
    const b = setInterval(() => setDossiers(s => s + 1), 5200)
    const c = setInterval(() => setObservers(s => Math.max(8, s + (Math.random() > 0.5 ? 1 : -1))), 3400)
    const d = setInterval(() => setRuns(s => Math.max(1, s + (Math.random() > 0.6 ? 1 : -1))), 1800)
    return () => { clearInterval(a); clearInterval(b); clearInterval(c); clearInterval(d) }
  }, [])

  const item = (label: string, value: string, glow = false) => (
    <div style={{ display: 'flex', alignItems: 'baseline', gap: 10 }}>
      <span
        style={{
          fontFamily: T.mono,
          fontSize: 9,
          letterSpacing: '0.22em',
          textTransform: 'uppercase',
          color: T.textFaint,
        }}
      >
        {label}
      </span>
      <span
        style={{
          fontFamily: T.serif,
          fontWeight: 800,
          fontSize: 20,
          letterSpacing: '-0.02em',
          color: glow ? T.ember : T.text,
          fontVariantNumeric: 'tabular-nums',
          textShadow: glow ? `0 0 22px rgba(255,106,61,0.4)` : 'none',
        }}
      >
        {value}
      </span>
    </div>
  )

  return (
    <div
      style={{
        display: 'flex',
        gap: 48,
        flexWrap: 'wrap',
        padding: '14px 22px',
        border: `0.5px solid ${T.edge}`,
        borderLeft: `2px solid ${T.ember}`,
        background: 'rgba(19,19,28,0.6)',
        backdropFilter: 'blur(10px)',
        WebkitBackdropFilter: 'blur(10px)',
      }}
    >
      {item('Scenarios at work', scenarios.toLocaleString(), true)}
      {item('Dossiers filed today', dossiers.toLocaleString())}
      {item('Observing now', observers.toLocaleString())}
      {item('Runs in progress', runs.toLocaleString())}
    </div>
  )
}

/* ═════════════════════════════════════════════════════════════════
 *  Distribution ladder — animated probability bars.
 * ═════════════════════════════════════════════════════════════════ */
function ProbabilityLadder() {
  const [active, setActive] = useState(-1)
  const total = DISTRIBUTION.reduce((a, b) => a + b.pct, 0)
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
      {DISTRIBUTION.map((row, idx) => {
        const pct = (row.pct / total) * 100
        const isActive = active === idx
        return (
          <Reveal key={row.label} delay={idx * 0.08}>
            <div
              onMouseEnter={() => setActive(idx)}
              onMouseLeave={() => setActive(-1)}
              style={{
                position: 'relative',
                padding: '18px 22px',
                border: `0.5px solid ${isActive ? T.edgeHi : T.edge}`,
                background: isActive ? 'rgba(27,27,38,0.75)' : 'rgba(13,13,20,0.55)',
                transition: 'border-color 240ms ease, background 240ms ease',
                display: 'grid',
                gridTemplateColumns: '140px 1fr 88px',
                alignItems: 'center',
                gap: 22,
                cursor: 'default',
                overflow: 'hidden',
              }}
            >
              <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
                <span
                  style={{
                    width: 8,
                    height: 8,
                    borderRadius: 1,
                    background: row.tint,
                    boxShadow: `0 0 12px ${row.tint}`,
                  }}
                />
                <span
                  style={{
                    fontFamily: T.mono,
                    fontSize: 10,
                    letterSpacing: '0.2em',
                    textTransform: 'uppercase',
                    color: T.text,
                    fontWeight: 500,
                  }}
                >
                  {row.label}
                </span>
              </div>

              <div
                style={{
                  position: 'relative',
                  height: 28,
                  background: 'rgba(255,255,255,0.04)',
                  border: `0.5px solid ${T.edge}`,
                  overflow: 'hidden',
                }}
              >
                <motion.div
                  initial={{ width: 0 }}
                  whileInView={{ width: `${pct}%` }}
                  viewport={{ once: true, margin: '-20px' }}
                  transition={{ duration: 1.1, delay: idx * 0.08, ease: [0.2, 0.8, 0.2, 1] }}
                  style={{
                    height: '100%',
                    background: `linear-gradient(90deg, ${row.tint}33, ${row.tint}cc)`,
                    borderRight: `1px solid ${row.tint}`,
                  }}
                />
                <AnimatePresence>
                  {isActive && (
                    <motion.span
                      initial={{ opacity: 0, x: 10 }}
                      animate={{ opacity: 1, x: 0 }}
                      exit={{ opacity: 0, x: 10 }}
                      style={{
                        position: 'absolute',
                        right: 12,
                        top: '50%',
                        transform: 'translateY(-50%)',
                        fontFamily: T.mono,
                        fontSize: 10,
                        letterSpacing: '0.16em',
                        color: T.textDim,
                        textTransform: 'uppercase',
                      }}
                    >
                      {row.note}
                    </motion.span>
                  )}
                </AnimatePresence>
              </div>

              <div
                style={{
                  fontFamily: T.serif,
                  fontSize: 32,
                  fontWeight: 800,
                  fontStyle: 'italic',
                  color: isActive ? row.tint : T.text,
                  letterSpacing: '-0.03em',
                  textAlign: 'right',
                  transition: 'color 240ms ease',
                  fontVariantNumeric: 'tabular-nums',
                }}
              >
                {row.pct}
                <span style={{ fontSize: 16, opacity: 0.55, marginLeft: 2 }}>%</span>
              </div>
            </div>
          </Reveal>
        )
      })}
    </div>
  )
}

/* ═════════════════════════════════════════════════════════════════
 *  Instrument pod — for "How the observatory sees"
 * ═════════════════════════════════════════════════════════════════ */
function InstrumentPod({
  index, tag, title, body, stat, statLabel,
}: { index: number; tag: string; title: string; body: string; stat: string; statLabel: string }) {
  const ref = useRef<HTMLDivElement>(null)
  const [hover, setHover] = useState(false)

  // micro-animation per pod: a tiny canvas demo
  const canvasRef = useRef<HTMLCanvasElement>(null)
  useEffect(() => {
    const c = canvasRef.current
    if (!c) return
    const ctx = c.getContext('2d')
    if (!ctx) return
    const dpr = Math.min(window.devicePixelRatio || 1, 1.75)
    const W = 260, H = 120
    c.width = W * dpr; c.height = H * dpr; c.style.width = W + 'px'; c.style.height = H + 'px'
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0)

    let raf = 0
    let t = 0
    const loop = () => {
      t += 0.02
      ctx.clearRect(0, 0, W, H)

      if (index === 0) {
        // Capture — a typing cursor over a soft baseline
        ctx.strokeStyle = 'rgba(243,238,228,0.18)'
        ctx.lineWidth = 0.6
        ctx.beginPath(); ctx.moveTo(18, 70); ctx.lineTo(W - 18, 70); ctx.stroke()
        // scratched words
        for (let i = 0; i < 12; i++) {
          const x = 18 + i * 20 + Math.sin(t + i) * 2
          ctx.strokeStyle = i < ((t * 3) % 14) ? T.ember : 'rgba(243,238,228,0.3)'
          ctx.lineWidth = 2
          ctx.beginPath()
          ctx.moveTo(x, 66 + Math.sin(i + t) * 2)
          ctx.lineTo(x + 14, 66 + Math.sin(i + t + 1) * 2)
          ctx.stroke()
        }
      } else if (index === 1) {
        // Populate — swirling agents
        for (let i = 0; i < 120; i++) {
          const a = i * 0.18 + t * 0.6
          const r = 10 + (i % 8) * 5 + Math.sin(t + i) * 3
          const x = W / 2 + Math.cos(a) * r
          const y = H / 2 + Math.sin(a) * r * 0.7
          ctx.fillStyle = i % 5 === 0 ? 'rgba(255,106,61,0.9)' : 'rgba(243,238,228,0.5)'
          ctx.beginPath(); ctx.arc(x, y, 1.2 + (i % 3) * 0.3, 0, Math.PI * 2); ctx.fill()
        }
      } else {
        // Report — three stacked bars filling
        const bars = [0.8, 0.55, 0.35]
        bars.forEach((b, i) => {
          const y = 25 + i * 26
          const fill = Math.min(1, (Math.sin(t - i) + 1) * 0.5 * 0.9 + 0.1) * b
          ctx.fillStyle = 'rgba(243,238,228,0.08)'
          ctx.fillRect(18, y, W - 36, 12)
          const grad = ctx.createLinearGradient(18, y, W - 36, y)
          grad.addColorStop(0, 'rgba(255,106,61,0.75)')
          grad.addColorStop(1, 'rgba(229,182,103,0.9)')
          ctx.fillStyle = grad
          ctx.fillRect(18, y, (W - 36) * fill, 12)
        })
      }

      raf = requestAnimationFrame(loop)
    }
    loop()
    return () => cancelAnimationFrame(raf)
  }, [index])

  return (
    <motion.div
      ref={ref}
      onMouseEnter={() => setHover(true)}
      onMouseLeave={() => setHover(false)}
      whileHover={{ y: -6 }}
      transition={{ duration: 0.35, ease: [0.2, 0.7, 0.2, 1] }}
      style={{
        position: 'relative',
        padding: 36,
        background: hover ? 'rgba(27,27,38,0.85)' : 'rgba(13,13,20,0.6)',
        border: `0.5px solid ${hover ? T.edgeHi : T.edge}`,
        overflow: 'hidden',
        height: '100%',
        display: 'flex',
        flexDirection: 'column',
      }}
    >
      {/* corner glow */}
      <div
        style={{
          position: 'absolute',
          top: -60,
          right: -60,
          width: 220,
          height: 220,
          background: `radial-gradient(circle, ${T.emberSoft}, transparent 70%)`,
          opacity: hover ? 1 : 0.55,
          transition: 'opacity 280ms ease',
          pointerEvents: 'none',
        }}
      />

      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', gap: 24, marginBottom: 28 }}>
        <span
          style={{
            fontFamily: T.mono,
            fontSize: 10,
            letterSpacing: '0.22em',
            textTransform: 'uppercase',
            color: T.ember,
            borderLeft: `2px solid ${T.ember}`,
            paddingLeft: 10,
          }}
        >
          {tag}
        </span>
        <span
          style={{
            fontFamily: T.serif,
            fontWeight: 900,
            fontSize: 60,
            fontStyle: 'italic',
            lineHeight: 1,
            color: 'rgba(255,255,255,0.05)',
            letterSpacing: '-0.04em',
          }}
        >
          0{index + 1}
        </span>
      </div>

      <h3
        style={{
          fontFamily: T.serif,
          fontWeight: 800,
          fontStyle: 'italic',
          fontSize: 28,
          lineHeight: 1.15,
          letterSpacing: '-0.02em',
          color: T.text,
          marginBottom: 16,
        }}
      >
        {title}
      </h3>
      <p
        style={{
          fontSize: 14,
          lineHeight: 1.8,
          color: T.textDim,
          marginBottom: 28,
          flex: 1,
        }}
      >
        {body}
      </p>

      <canvas ref={canvasRef} style={{ width: '100%', height: 120, marginBottom: 20, borderTop: `0.5px solid ${T.edge}`, paddingTop: 10 }} />

      <div style={{ display: 'flex', alignItems: 'baseline', gap: 14, borderTop: `0.5px solid ${T.edge}`, paddingTop: 20 }}>
        <span
          style={{
            fontFamily: T.serif,
            fontWeight: 900,
            fontStyle: 'italic',
            fontSize: 34,
            color: T.ember,
            letterSpacing: '-0.03em',
            lineHeight: 1,
            textShadow: `0 0 24px rgba(255,106,61,0.3)`,
          }}
        >
          {stat}
        </span>
        <span
          style={{
            fontFamily: T.mono,
            fontSize: 10,
            letterSpacing: '0.2em',
            textTransform: 'uppercase',
            color: T.textFaint,
          }}
        >
          {statLabel}
        </span>
      </div>
    </motion.div>
  )
}

/* ═════════════════════════════════════════════════════════════════
 *  Report sheet — sample dossier visual, slightly tilted
 * ═════════════════════════════════════════════════════════════════ */
function ReportSheet() {
  return (
    <motion.div
      initial={{ opacity: 0, y: 40, rotateX: 8, rotateY: -8 }}
      whileInView={{ opacity: 1, y: 0, rotateX: 0, rotateY: 0 }}
      viewport={{ once: true, margin: '-40px' }}
      transition={{ duration: 1, ease: [0.2, 0.7, 0.2, 1] }}
      whileHover={{ rotateX: 2, rotateY: -3, y: -6 }}
      style={{
        position: 'relative',
        background: 'linear-gradient(155deg, rgba(27,27,38,0.95), rgba(13,13,20,0.85))',
        border: `0.5px solid ${T.edgeHi}`,
        padding: '48px 52px 44px',
        boxShadow:
          '0 40px 120px rgba(0,0,0,0.6), 0 0 1px rgba(255,106,61,0.2), inset 0 1px 0 rgba(255,255,255,0.04)',
        transformStyle: 'preserve-3d',
        perspective: 1200,
      }}
    >
      {/* stamp */}
      <div
        style={{
          position: 'absolute',
          top: 28,
          right: 32,
          display: 'flex',
          flexDirection: 'column',
          alignItems: 'flex-end',
          gap: 4,
        }}
      >
        <div
          style={{
            border: `1.5px solid ${T.ember}`,
            padding: '4px 10px',
            fontFamily: T.mono,
            fontSize: 9,
            letterSpacing: '0.24em',
            textTransform: 'uppercase',
            color: T.ember,
            fontWeight: 700,
            transform: 'rotate(-4deg)',
          }}
        >
          Filed · 04.2026
        </div>
        <span style={{ fontFamily: T.mono, fontSize: 8, letterSpacing: '0.2em', color: T.textFaint, textTransform: 'uppercase' }}>
          Dossier № 04/18-A
        </span>
      </div>

      {/* header */}
      <div style={{ marginBottom: 32, borderBottom: `0.5px solid ${T.edge}`, paddingBottom: 22 }}>
        <span style={{ fontFamily: T.mono, fontSize: 10, letterSpacing: '0.22em', color: T.textFaint, textTransform: 'uppercase' }}>
          Specimen dossier · A D2C skincare bet
        </span>
        <h3
          style={{
            fontFamily: T.serif,
            fontWeight: 800,
            fontStyle: 'italic',
            fontSize: 34,
            color: T.text,
            letterSpacing: '-0.03em',
            marginTop: 10,
            lineHeight: 1.1,
          }}
        >
          Survive rate: <span style={{ color: T.gold }}>32%</span>. <br />
          The idea does not die. The <span style={{ color: T.ember }}>pricing does.</span>
        </h3>
      </div>

      {/* three columns */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 28, marginBottom: 28 }}>
        {[
          {
            head: 'Top failure mode',
            val: 'Refill fatigue',
            sub: 'Reorder drops 61% after month 3. Cohort loses 70% by m-6.',
            tint: T.dim,
          },
          {
            head: 'Strongest lever',
            val: 'Subscribe & save',
            sub: 'Raises LTV by 2.4×. Reduces churn by 38 pts.',
            tint: T.jade,
          },
          {
            head: 'Pricing truth',
            val: '+40% acceptable',
            sub: '71% of buyers still convert at ₹1,499. Volume drop: 19%.',
            tint: T.gold,
          },
        ].map(col => (
          <div key={col.head} style={{ borderLeft: `2px solid ${col.tint}`, paddingLeft: 16 }}>
            <div style={{ fontFamily: T.mono, fontSize: 9, letterSpacing: '0.22em', textTransform: 'uppercase', color: T.textFaint, marginBottom: 10 }}>
              {col.head}
            </div>
            <div style={{ fontFamily: T.serif, fontWeight: 800, fontStyle: 'italic', fontSize: 22, color: col.tint, letterSpacing: '-0.02em', marginBottom: 8 }}>
              {col.val}
            </div>
            <p style={{ fontSize: 12, lineHeight: 1.65, color: T.textDim }}>{col.sub}</p>
          </div>
        ))}
      </div>

      {/* interventions list */}
      <div
        style={{
          borderTop: `0.5px solid ${T.edge}`,
          paddingTop: 22,
          display: 'grid',
          gridTemplateColumns: '1fr 1fr',
          gap: 14,
        }}
      >
        <div style={{ fontFamily: T.mono, fontSize: 10, letterSpacing: '0.22em', textTransform: 'uppercase', color: T.ember, gridColumn: '1 / -1', marginBottom: 10 }}>
          Interventions · ranked by odds-shift
        </div>
        {[
          { n: 'I', t: 'Bundle three-month supply at ₹3,999', d: '+14 pts to survival' },
          { n: 'II', t: 'Launch refill reminders at week 9', d: '+9 pts to repeat' },
          { n: 'III', t: 'Raise hero SKU to ₹1,499', d: '+21% gross margin' },
          { n: 'IV', t: 'Retire Instagram-only channel', d: '+6 pts to payback' },
        ].map(i => (
          <div key={i.n} style={{ display: 'flex', alignItems: 'center', gap: 14, padding: '10px 0', borderBottom: `0.5px solid ${T.edge}` }}>
            <span style={{ fontFamily: T.serif, fontStyle: 'italic', fontWeight: 700, fontSize: 18, color: T.textFaint, minWidth: 28 }}>
              {i.n}
            </span>
            <span style={{ flex: 1, fontSize: 13, color: T.text, lineHeight: 1.5 }}>{i.t}</span>
            <span style={{ fontFamily: T.mono, fontSize: 10, color: T.jade, letterSpacing: '0.12em', textTransform: 'uppercase' }}>
              {i.d}
            </span>
          </div>
        ))}
      </div>

      {/* signature */}
      <div
        style={{
          marginTop: 28,
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'center',
          fontFamily: T.mono,
          fontSize: 9,
          letterSpacing: '0.22em',
          textTransform: 'uppercase',
          color: T.textFaint,
        }}
      >
        <span>Compiled by Architect N-04</span>
        <span>Run: 10,000 agents · 14 scenarios · 2,430 paths</span>
      </div>
    </motion.div>
  )
}

/* ═════════════════════════════════════════════════════════════════
 *  Main page
 * ═════════════════════════════════════════════════════════════════ */
export default function LandingPage() {
  const heroRef = useRef<HTMLDivElement>(null)

  // hero parallax
  const { scrollYProgress: heroProg } = useScroll({ target: heroRef, offset: ['start start', 'end start'] })
  const heroTitleY = useTransform(heroProg, [0, 1], [0, -40])
  const heroBgY = useTransform(heroProg, [0, 1], [0, 80])
  const heroOpacity = useTransform(heroProg, [0, 0.75], [1, 0])

  // auth state
  const user = useAuthStore(s => s.user)
  const isHydrated = useAuthStore(s => s.isHydrated)
  const logout = useLogout()
  const isAuthed =
    Boolean(user) || (isHydrated && typeof window !== 'undefined' && authLib.isAuthenticated())

  const [authOpen, setAuthOpen] = useState(false)
  const [authMode, setAuthMode] = useState<'login' | 'signup'>('signup')
  const openAuth = (m: 'login' | 'signup') => { setAuthMode(m); setAuthOpen(true) }
  const signOut = () => { logout() }

  // prompt input — just a vanity interaction; on submit, open auth
  const [prompt, setPrompt] = useState('')
  const [fieldMode, setFieldMode] = useState<FieldMode>('drift')
  const [fieldTrigger, setFieldTrigger] = useState(0)
  const runObservatory = () => {
    setFieldMode('cluster')
    setFieldTrigger(t => t + 1)
    setTimeout(() => openAuth('signup'), 900)
  }

  // "now" clock
  const [now, setNow] = useState<Date | null>(null)
  useEffect(() => {
    setNow(new Date())
    const i = setInterval(() => setNow(new Date()), 1000)
    return () => clearInterval(i)
  }, [])
  const nowStr = useMemo(() => {
    if (!now) return '—'
    return now.toLocaleTimeString('en-GB', { hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false })
  }, [now])

  return (
    <div
      style={{
        background: T.void,
        color: T.text,
        minHeight: '100vh',
        fontFamily: "var(--font-body, 'DM Sans', sans-serif)",
        fontWeight: 300,
        position: 'relative',
        overflow: 'hidden',
      }}
    >
      <CursorHalo />
      <ScrollProgress />

      <TopBar
        isAuthed={isAuthed}
        isHydrated={isHydrated}
        onSignIn={() => openAuth('login')}
        onSignUp={() => openAuth('signup')}
        onLogout={signOut}
        userEmail={user?.email}
      />

      {/* ═══════════════════════════════════════════════════════════
          01 · HERO — The Observatory
         ═══════════════════════════════════════════════════════════ */}
      <section
        ref={heroRef}
        style={{
          position: 'relative',
          minHeight: '100vh',
          display: 'flex',
          alignItems: 'center',
          overflow: 'hidden',
          isolation: 'isolate',
        }}
      >
        {/* particle field */}
        <motion.div style={{ position: 'absolute', inset: 0, y: heroBgY }}>
          <ObservatoryField mode={fieldMode} trigger={fieldTrigger} />
        </motion.div>

        {/* gradient washes */}
        <div
          aria-hidden
          style={{
            position: 'absolute',
            inset: 0,
            background:
              `radial-gradient(ellipse 80% 60% at 50% 30%, rgba(255,106,61,0.14), transparent 60%),
               radial-gradient(ellipse 90% 70% at 20% 85%, rgba(127,255,166,0.05), transparent 60%),
               linear-gradient(180deg, rgba(6,6,10,0.35), rgba(6,6,10,0) 30%, rgba(6,6,10,0.65) 100%)`,
            pointerEvents: 'none',
            zIndex: 1,
          }}
        />

        {/* vertical deco rails */}
        <div aria-hidden style={{ position: 'absolute', top: 0, bottom: 0, left: 40, width: '0.5px', background: T.edge, zIndex: 1 }} />
        <div aria-hidden style={{ position: 'absolute', top: 0, bottom: 0, right: 40, width: '0.5px', background: T.edge, zIndex: 1 }} />

        {/* left ruler text (rotated) */}
        <div
          aria-hidden
          style={{
            position: 'absolute',
            left: 18,
            top: '50%',
            transform: 'translateY(-50%) rotate(-90deg)',
            transformOrigin: 'center',
            fontFamily: T.mono,
            fontSize: 9,
            letterSpacing: '0.5em',
            color: T.textFaint,
            textTransform: 'uppercase',
            whiteSpace: 'nowrap',
            zIndex: 2,
          }}
        >
          Volume i · issue 04 · a live simulation
        </div>

        {/* right — running clock */}
        <div
          aria-hidden
          style={{
            position: 'absolute',
            right: 18,
            top: '50%',
            transform: 'translateY(-50%) rotate(90deg)',
            transformOrigin: 'center',
            fontFamily: T.mono,
            fontSize: 9,
            letterSpacing: '0.5em',
            color: T.textFaint,
            textTransform: 'uppercase',
            whiteSpace: 'nowrap',
            zIndex: 2,
            fontVariantNumeric: 'tabular-nums',
          }}
        >
          {nowStr} IST · the observatory is awake
        </div>

        {/* content */}
        <motion.div
          style={{
            position: 'relative',
            zIndex: 2,
            margin: '0 auto',
            padding: '140px 80px 80px',
            maxWidth: 1400,
            width: '100%',
            y: heroTitleY,
            opacity: heroOpacity,
          }}
        >
          {/* kicker */}
          <motion.div
            initial={{ opacity: 0, y: 10 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.6 }}
            style={{ display: 'flex', alignItems: 'center', gap: 14, marginBottom: 36 }}
          >
            <Radio size={12} color={T.ember} />
            <span
              style={{
                fontFamily: T.mono,
                fontSize: 10,
                letterSpacing: '0.36em',
                textTransform: 'uppercase',
                color: T.textDim,
              }}
            >
              Live from the observatory · a simulation of your next decision
            </span>
          </motion.div>

          {/* headline */}
          <motion.h1
            initial={{ opacity: 0, y: 24 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.9, delay: 0.15 }}
            style={{
              fontFamily: T.serif,
              fontWeight: 900,
              fontSize: 'clamp(60px, 9vw, 170px)',
              lineHeight: 0.92,
              letterSpacing: '-0.04em',
              color: T.text,
              margin: 0,
              maxWidth: 1280,
            }}
          >
            Will your idea<br />
            <span style={{ color: T.textDim, fontStyle: 'italic' }}>
              <CyclingQuestion />
            </span>
          </motion.h1>

          {/* lede */}
          <motion.p
            initial={{ opacity: 0, y: 16 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.8, delay: 0.55 }}
            style={{
              marginTop: 48,
              fontSize: 18,
              lineHeight: 1.7,
              color: T.textDim,
              maxWidth: 640,
              fontWeight: 300,
            }}
          >
            TheCee runs your startup through a million synthetic markets before you commit a rupee.
            Architects cast cohorts, a press of agents votes on your price, channel, and story —
            and you get the autopsy before the burial. <span style={{ color: T.text }}>Filed in under two minutes.</span>
          </motion.p>

          {/* prompt */}
          <motion.div
            initial={{ opacity: 0, y: 16 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.9, delay: 0.8 }}
            style={{ marginTop: 48, maxWidth: 780 }}
          >
            <div style={{ fontFamily: T.mono, fontSize: 10, letterSpacing: '0.3em', textTransform: 'uppercase', color: T.textFaint, marginBottom: 12 }}>
              Begin &nbsp;·&nbsp; type the idea you are afraid to put on paper
            </div>
            <form
              onSubmit={e => { e.preventDefault(); runObservatory() }}
              style={{
                position: 'relative',
                display: 'grid',
                gridTemplateColumns: '1fr auto',
                alignItems: 'stretch',
                background: 'rgba(13,13,20,0.72)',
                border: `0.5px solid ${T.edgeHi}`,
                backdropFilter: 'blur(18px)',
                WebkitBackdropFilter: 'blur(18px)',
                boxShadow: `0 30px 80px rgba(0,0,0,0.55), 0 0 0 1px ${T.emberSoft}`,
              }}
            >
              <input
                value={prompt}
                onChange={e => setPrompt(e.target.value)}
                onFocus={() => setFieldMode('cluster')}
                onBlur={() => setFieldMode('drift')}
                placeholder="A skincare brand for night-shift workers in Indian cities…"
                style={{
                  background: 'transparent',
                  border: 'none',
                  outline: 'none',
                  padding: '22px 26px',
                  color: T.text,
                  fontFamily: "var(--font-body, 'DM Sans', sans-serif)",
                  fontSize: 17,
                  fontWeight: 300,
                  letterSpacing: '-0.005em',
                  width: '100%',
                }}
              />
              <button
                type="submit"
                style={{
                  background: T.ember,
                  color: T.void,
                  border: 'none',
                  padding: '0 28px',
                  fontFamily: T.mono,
                  fontSize: 11,
                  letterSpacing: '0.22em',
                  textTransform: 'uppercase',
                  fontWeight: 700,
                  cursor: 'pointer',
                  display: 'flex',
                  alignItems: 'center',
                  gap: 10,
                  transition: 'filter 180ms ease, transform 180ms ease',
                }}
                onMouseEnter={e => { e.currentTarget.style.filter = 'brightness(1.1)'; e.currentTarget.style.transform = 'translateX(2px)' }}
                onMouseLeave={e => { e.currentTarget.style.filter = 'none'; e.currentTarget.style.transform = 'translateX(0)' }}
              >
                <Play size={12} fill={T.void} />
                Run 10,000 <ArrowRight size={12} />
              </button>
            </form>
            <div
              style={{
                marginTop: 12,
                display: 'flex',
                gap: 18,
                flexWrap: 'wrap',
                fontFamily: T.mono,
                fontSize: 10,
                letterSpacing: '0.18em',
                textTransform: 'uppercase',
                color: T.textFaint,
              }}
            >
              <span>↵ No card required</span>
              <span>·</span>
              <span>First run is free</span>
              <span>·</span>
              <span>You keep everything you file</span>
            </div>
          </motion.div>

          {/* ticker */}
          <motion.div
            initial={{ opacity: 0, y: 18 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 1, delay: 1.1 }}
            style={{ marginTop: 56, maxWidth: 900 }}
          >
            <RunningTicker />
          </motion.div>
        </motion.div>

        {/* scroll hint */}
        <motion.div
          aria-hidden
          initial={{ opacity: 0 }}
          animate={{ opacity: [0.15, 0.55, 0.15] }}
          transition={{ duration: 2.4, repeat: Infinity, ease: 'easeInOut', delay: 1.5 }}
          style={{
            position: 'absolute',
            bottom: 28,
            left: '50%',
            transform: 'translateX(-50%)',
            display: 'flex',
            flexDirection: 'column',
            alignItems: 'center',
            gap: 8,
            fontFamily: T.mono,
            fontSize: 9,
            letterSpacing: '0.4em',
            textTransform: 'uppercase',
            color: T.textDim,
            zIndex: 3,
          }}
        >
          <span>Scroll · watch the distribution unfold</span>
          <div style={{ width: 1, height: 34, background: `linear-gradient(180deg, ${T.ember}, transparent)` }} />
        </motion.div>
      </section>

      {/* ═══════════════════════════════════════════════════════════
          02 · MANIFESTO — giant marquee + statement
         ═══════════════════════════════════════════════════════════ */}
      <section
        style={{
          position: 'relative',
          padding: '140px 0 100px',
          borderTop: `0.5px solid ${T.edge}`,
          borderBottom: `0.5px solid ${T.edge}`,
          background: `linear-gradient(180deg, ${T.void} 0%, ${T.voidRaised} 100%)`,
          overflow: 'hidden',
        }}
      >
        {/* marquee */}
        <div
          style={{
            position: 'relative',
            display: 'flex',
            overflow: 'hidden',
            maskImage: 'linear-gradient(90deg, transparent, #000 8%, #000 92%, transparent)',
            WebkitMaskImage: 'linear-gradient(90deg, transparent, #000 8%, #000 92%, transparent)',
            marginBottom: 100,
          }}
          aria-hidden
        >
          <motion.div
            animate={{ x: ['0%', '-50%'] }}
            transition={{ duration: 42, repeat: Infinity, ease: 'linear' }}
            style={{
              display: 'flex',
              gap: 64,
              whiteSpace: 'nowrap',
              fontFamily: T.serif,
              fontStyle: 'italic',
              fontWeight: 900,
              fontSize: 'clamp(80px, 12vw, 210px)',
              color: 'rgba(243,238,228,0.06)',
              letterSpacing: '-0.04em',
              paddingRight: 64,
            }}
          >
            {Array.from({ length: 2 }).map((_, i) => (
              <span key={i} style={{ display: 'inline-flex', gap: 64 }}>
                <span>know before you build</span>
                <span style={{ color: T.emberSoft }}>·</span>
                <span style={{ color: 'rgba(243,238,228,0.14)' }}>know before you build</span>
                <span style={{ color: T.emberSoft }}>·</span>
                <span>know before you build</span>
                <span style={{ color: T.emberSoft }}>·</span>
              </span>
            ))}
          </motion.div>
        </div>

        <div style={{ maxWidth: 1280, margin: '0 auto', padding: '0 80px' }}>
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1.4fr', gap: 80, alignItems: 'flex-start' }}>
            <Reveal>
              <div
                style={{
                  fontFamily: T.mono,
                  fontSize: 10,
                  letterSpacing: '0.3em',
                  textTransform: 'uppercase',
                  color: T.ember,
                  display: 'flex',
                  alignItems: 'center',
                  gap: 10,
                  marginBottom: 24,
                }}
              >
                <span style={{ width: 24, height: 1, background: T.ember }} />
                The thesis
              </div>
              <p
                style={{
                  fontFamily: T.serif,
                  fontWeight: 300,
                  fontStyle: 'italic',
                  fontSize: 22,
                  lineHeight: 1.45,
                  color: T.text,
                  letterSpacing: '-0.005em',
                  maxWidth: 420,
                }}
              >
                Most startups do not fail for a lack of effort. <br />
                They fail for a lack of <span style={{ color: T.ember }}>evidence</span>.
              </p>
            </Reveal>
            <Reveal delay={0.15}>
              <p
                style={{
                  fontSize: 21,
                  lineHeight: 1.75,
                  color: T.textDim,
                  fontWeight: 300,
                }}
              >
                The founder's most honest tool is not conviction, it is <em style={{ color: T.text, fontStyle: 'italic' }}>counterfactual rehearsal</em>. You do not need another advisor; you need a thousand of them, disagreeing, in a room you can walk through before Monday morning. We built the room. It is open.
              </p>
            </Reveal>
          </div>
        </div>
      </section>

      {/* ═══════════════════════════════════════════════════════════
          03 · INSTRUMENTS — three pods
         ═══════════════════════════════════════════════════════════ */}
      <section
        id="how"
        style={{
          position: 'relative',
          padding: '140px 0',
          background: T.void,
          borderBottom: `0.5px solid ${T.edge}`,
        }}
      >
        <div style={{ maxWidth: 1400, margin: '0 auto', padding: '0 80px' }}>
          <Reveal>
            <div style={{ display: 'flex', alignItems: 'center', gap: 14, marginBottom: 28 }}>
              <span style={{ width: 28, height: 1, background: T.ember }} />
              <span style={{ fontFamily: T.mono, fontSize: 10, letterSpacing: '0.3em', textTransform: 'uppercase', color: T.ember }}>
                The instruments · how we see
              </span>
            </div>
            <h2
              style={{
                fontFamily: T.serif,
                fontWeight: 900,
                fontSize: 'clamp(44px, 5.5vw, 82px)',
                lineHeight: 1.02,
                letterSpacing: '-0.035em',
                color: T.text,
                maxWidth: 1100,
                marginBottom: 72,
              }}
            >
              Three instruments. <span style={{ fontStyle: 'italic', color: T.textDim }}>One truth</span>
              <span style={{ color: T.ember }}>.</span>
            </h2>
          </Reveal>

          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 24 }}>
            {INSTRUMENTS.map((p, i) => (
              <Reveal key={p.tag} delay={i * 0.1}>
                <InstrumentPod index={i} {...p} />
              </Reveal>
            ))}
          </div>
        </div>
      </section>

      {/* ═══════════════════════════════════════════════════════════
          04 · DISTRIBUTION — the probability ladder
         ═══════════════════════════════════════════════════════════ */}
      <section
        style={{
          position: 'relative',
          padding: '140px 0',
          background: `linear-gradient(180deg, ${T.void}, ${T.voidRaised})`,
          borderBottom: `0.5px solid ${T.edge}`,
        }}
      >
        <div style={{ maxWidth: 1280, margin: '0 auto', padding: '0 80px' }}>
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1.4fr', gap: 80, alignItems: 'flex-start' }}>
            <Reveal>
              <div style={{ display: 'flex', alignItems: 'center', gap: 14, marginBottom: 24 }}>
                <span style={{ width: 28, height: 1, background: T.ember }} />
                <span style={{ fontFamily: T.mono, fontSize: 10, letterSpacing: '0.3em', textTransform: 'uppercase', color: T.ember }}>
                  The distribution
                </span>
              </div>
              <h2
                style={{
                  fontFamily: T.serif,
                  fontWeight: 900,
                  fontStyle: 'italic',
                  fontSize: 'clamp(42px, 4.4vw, 64px)',
                  lineHeight: 1.04,
                  letterSpacing: '-0.03em',
                  color: T.text,
                  marginBottom: 28,
                }}
              >
                Every idea has a <span style={{ color: T.ember, fontStyle: 'normal' }}>shape</span>.
                <br />
                We show you yours.
              </h2>
              <p style={{ fontSize: 16, lineHeight: 1.8, color: T.textDim, maxWidth: 420, marginBottom: 32 }}>
                The observatory does not hand you a thumbs-up or thumbs-down. It hands you the whole distribution — the shape of all futures your idea could walk into — and the single cheapest move to bend it toward the one you want.
              </p>
              <div style={{ fontFamily: T.mono, fontSize: 10, letterSpacing: '0.2em', textTransform: 'uppercase', color: T.textFaint }}>
                Sample cohort ·<span style={{ color: T.ember }}> Urban D2C bet</span> · 10,000 agents
              </div>
            </Reveal>

            <ProbabilityLadder />
          </div>
        </div>
      </section>

      {/* ═══════════════════════════════════════════════════════════
          05 · DOSSIER — the report, up close
         ═══════════════════════════════════════════════════════════ */}
      <section
        id="dossier"
        style={{
          position: 'relative',
          padding: '140px 0',
          background: T.void,
          borderBottom: `0.5px solid ${T.edge}`,
          overflow: 'hidden',
        }}
      >
        {/* ambient glow behind */}
        <div
          aria-hidden
          style={{
            position: 'absolute',
            top: '30%',
            left: '50%',
            transform: 'translateX(-50%)',
            width: '80vw',
            height: '80vw',
            maxWidth: 1400,
            maxHeight: 1400,
            background: `radial-gradient(circle, ${T.emberSoft}, transparent 60%)`,
            pointerEvents: 'none',
            zIndex: 0,
          }}
        />

        <div style={{ position: 'relative', zIndex: 1, maxWidth: 1280, margin: '0 auto', padding: '0 80px' }}>
          <Reveal>
            <div style={{ display: 'flex', alignItems: 'center', gap: 14, marginBottom: 28, justifyContent: 'center' }}>
              <span style={{ width: 28, height: 1, background: T.ember }} />
              <span style={{ fontFamily: T.mono, fontSize: 10, letterSpacing: '0.3em', textTransform: 'uppercase', color: T.ember }}>
                A specimen dossier
              </span>
              <span style={{ width: 28, height: 1, background: T.ember }} />
            </div>
            <h2
              style={{
                fontFamily: T.serif,
                fontWeight: 900,
                fontSize: 'clamp(40px, 5vw, 78px)',
                lineHeight: 1.02,
                letterSpacing: '-0.035em',
                color: T.text,
                textAlign: 'center',
                marginBottom: 72,
              }}
            >
              The report that <em style={{ color: T.ember }}>earns its keep</em>.
            </h2>
          </Reveal>

          <ReportSheet />

          <div style={{ textAlign: 'center', marginTop: 48 }}>
            <button
              type="button"
              onClick={() => openAuth('signup')}
              style={{
                display: 'inline-flex',
                alignItems: 'center',
                gap: 12,
                background: 'transparent',
                border: `0.5px solid ${T.edgeHi}`,
                color: T.text,
                padding: '16px 28px',
                fontFamily: T.mono,
                fontSize: 11,
                letterSpacing: '0.22em',
                textTransform: 'uppercase',
                cursor: 'pointer',
                fontWeight: 500,
                transition: 'all 240ms ease',
              }}
              onMouseEnter={e => { e.currentTarget.style.borderColor = T.ember; e.currentTarget.style.color = T.ember }}
              onMouseLeave={e => { e.currentTarget.style.borderColor = T.edgeHi; e.currentTarget.style.color = T.text }}
            >
              File your own dossier, free <ArrowUpRight size={14} />
            </button>
          </div>
        </div>
      </section>

      {/* ═══════════════════════════════════════════════════════════
          06 · VOICES — testimonials in dark cards
         ═══════════════════════════════════════════════════════════ */}
      <section
        style={{
          position: 'relative',
          padding: '140px 0',
          background: T.voidRaised,
          borderBottom: `0.5px solid ${T.edge}`,
        }}
      >
        <div style={{ maxWidth: 1280, margin: '0 auto', padding: '0 80px' }}>
          <Reveal>
            <div style={{ display: 'flex', alignItems: 'center', gap: 14, marginBottom: 28 }}>
              <span style={{ width: 28, height: 1, background: T.ember }} />
              <span style={{ fontFamily: T.mono, fontSize: 10, letterSpacing: '0.3em', textTransform: 'uppercase', color: T.ember }}>
                Transmissions
              </span>
            </div>
            <h2
              style={{
                fontFamily: T.serif,
                fontWeight: 900,
                fontSize: 'clamp(40px, 5vw, 72px)',
                lineHeight: 1.02,
                letterSpacing: '-0.035em',
                color: T.text,
                marginBottom: 72,
                maxWidth: 900,
              }}
            >
              From the founders who <em style={{ color: T.textDim }}>could not afford</em> to guess.
            </h2>
          </Reveal>

          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(2, 1fr)', gap: 24 }}>
            {VOICES.map((v, i) => (
              <Reveal key={v.title} delay={i * 0.08}>
                <VoiceCard {...v} />
              </Reveal>
            ))}
          </div>
        </div>
      </section>

      {/* ═══════════════════════════════════════════════════════════
          07 · TIERS — access levels
         ═══════════════════════════════════════════════════════════ */}
      <section
        id="pricing"
        style={{
          position: 'relative',
          padding: '140px 0',
          background: T.void,
          borderBottom: `0.5px solid ${T.edge}`,
        }}
      >
        <div style={{ maxWidth: 1280, margin: '0 auto', padding: '0 80px' }}>
          <Reveal>
            <div style={{ display: 'flex', alignItems: 'center', gap: 14, marginBottom: 28 }}>
              <span style={{ width: 28, height: 1, background: T.ember }} />
              <span style={{ fontFamily: T.mono, fontSize: 10, letterSpacing: '0.3em', textTransform: 'uppercase', color: T.ember }}>
                Tiers of access
              </span>
            </div>
            <h2
              style={{
                fontFamily: T.serif,
                fontWeight: 900,
                fontSize: 'clamp(40px, 5vw, 72px)',
                lineHeight: 1.02,
                letterSpacing: '-0.035em',
                color: T.text,
                marginBottom: 72,
                maxWidth: 900,
              }}
            >
              Three ways <em style={{ color: T.ember }}>in</em>.
              <span style={{ color: T.textDim }}> One observatory.</span>
            </h2>
          </Reveal>

          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 24 }}>
            {TIERS.map((t, i) => (
              <Reveal key={t.name} delay={i * 0.1}>
                <TierCard tier={t} onClick={() => openAuth('signup')} />
              </Reveal>
            ))}
          </div>

          <div
            style={{
              marginTop: 56,
              fontFamily: T.mono,
              fontSize: 10,
              letterSpacing: '0.22em',
              textTransform: 'uppercase',
              color: T.textFaint,
              textAlign: 'center',
            }}
          >
            All tiers include the pre-mortem report, the distribution, and the full set of interventions.
          </div>
        </div>
      </section>

      {/* ═══════════════════════════════════════════════════════════
          08 · FINAL CTA — massive, cinematic
         ═══════════════════════════════════════════════════════════ */}
      <section
        style={{
          position: 'relative',
          padding: '200px 0',
          background: `linear-gradient(180deg, ${T.void} 0%, #000 100%)`,
          overflow: 'hidden',
        }}
      >
        {/* aurora */}
        <motion.div
          aria-hidden
          animate={{ opacity: [0.35, 0.65, 0.35] }}
          transition={{ duration: 7, repeat: Infinity, ease: 'easeInOut' }}
          style={{
            position: 'absolute',
            top: '20%',
            left: '50%',
            transform: 'translateX(-50%)',
            width: '120vw',
            height: 520,
            background:
              `radial-gradient(ellipse 60% 80% at 30% 50%, rgba(255,106,61,0.22), transparent 60%),
               radial-gradient(ellipse 50% 70% at 70% 50%, rgba(229,182,103,0.12), transparent 60%)`,
            pointerEvents: 'none',
            filter: 'blur(30px)',
          }}
        />

        <div style={{ position: 'relative', maxWidth: 1280, margin: '0 auto', padding: '0 80px', textAlign: 'center' }}>
          <Reveal>
            <div
              style={{
                fontFamily: T.mono,
                fontSize: 11,
                letterSpacing: '0.4em',
                textTransform: 'uppercase',
                color: T.ember,
                marginBottom: 40,
                display: 'inline-flex',
                alignItems: 'center',
                gap: 12,
              }}
            >
              <Sparkles size={14} />
              The press is open
              <Sparkles size={14} />
            </div>
          </Reveal>
          <Reveal delay={0.1}>
            <h2
              style={{
                fontFamily: T.serif,
                fontWeight: 900,
                fontStyle: 'italic',
                fontSize: 'clamp(56px, 9vw, 160px)',
                lineHeight: 0.95,
                letterSpacing: '-0.04em',
                color: T.text,
                marginBottom: 36,
              }}
            >
              Your next decision<br />
              <span style={{ color: T.textFaint }}>deserves</span> <span style={{ color: T.ember, textShadow: `0 0 64px rgba(255,106,61,0.35)` }}>certainty</span>.
            </h2>
          </Reveal>
          <Reveal delay={0.2}>
            <p
              style={{
                fontSize: 18,
                lineHeight: 1.7,
                color: T.textDim,
                maxWidth: 620,
                margin: '0 auto 56px',
                fontWeight: 300,
              }}
            >
              Stop planning. Stop guessing. Stop asking the wrong friends on the wrong weekends. Walk into the room. The lights are on.
            </p>
          </Reveal>
          <Reveal delay={0.3}>
            <button
              type="button"
              onClick={() => openAuth('signup')}
              style={{
                display: 'inline-flex',
                alignItems: 'center',
                gap: 14,
                padding: '22px 44px',
                background: T.ember,
                color: T.void,
                border: 'none',
                fontFamily: T.mono,
                fontSize: 12,
                letterSpacing: '0.28em',
                textTransform: 'uppercase',
                fontWeight: 700,
                cursor: 'pointer',
                boxShadow: `0 30px 90px rgba(255,106,61,0.35), 0 0 0 1px rgba(255,106,61,0.6)`,
                transition: 'transform 220ms ease, filter 220ms ease',
              }}
              onMouseEnter={e => { e.currentTarget.style.transform = 'translateY(-3px)'; e.currentTarget.style.filter = 'brightness(1.08)' }}
              onMouseLeave={e => { e.currentTarget.style.transform = 'translateY(0)'; e.currentTarget.style.filter = 'none' }}
            >
              File your first dossier <ArrowRight size={14} />
            </button>
          </Reveal>
        </div>
      </section>

      {/* ═══════════════════════════════════════════════════════════
          FOOTER
         ═══════════════════════════════════════════════════════════ */}
      <footer style={{ background: '#000', padding: '64px 80px 36px' }}>
        <div style={{ maxWidth: 1280, margin: '0 auto' }}>
          <div
            style={{
              display: 'grid',
              gridTemplateColumns: '1.5fr 1fr 1fr 1fr',
              gap: 48,
              paddingBottom: 48,
              borderBottom: `0.5px solid ${T.edge}`,
            }}
          >
            <div>
              <div
                style={{
                  fontFamily: T.serif,
                  fontWeight: 900,
                  fontStyle: 'italic',
                  fontSize: 30,
                  color: T.text,
                  letterSpacing: '-0.035em',
                  marginBottom: 14,
                }}
              >
                TheCee
              </div>
              <p style={{ fontSize: 13, color: T.textFaint, lineHeight: 1.7, maxWidth: 320 }}>
                The observatory for founders who cannot afford to guess. Printed in IST, on the Internet, since 2026.
              </p>
            </div>

            {[
              { h: 'Observatory', items: ['The instruments', 'The distribution', 'A sample dossier', 'Tiers of access'] },
              { h: 'Press room', items: ['Editor', 'Methodology', 'Press kit', 'Careers'] },
              { h: 'Colophon', items: ['Privacy', 'Terms', 'Status', 'Contact'] },
            ].map(col => (
              <div key={col.h}>
                <div style={{ fontFamily: T.mono, fontSize: 9, letterSpacing: '0.3em', textTransform: 'uppercase', color: T.textFaint, marginBottom: 16 }}>
                  {col.h}
                </div>
                {col.items.map(it => (
                  <a
                    key={it}
                    href="#"
                    style={{
                      display: 'block',
                      padding: '6px 0',
                      fontSize: 13,
                      color: T.textDim,
                      textDecoration: 'none',
                      transition: 'color 220ms ease',
                    }}
                    onMouseEnter={e => (e.currentTarget.style.color = T.ember)}
                    onMouseLeave={e => (e.currentTarget.style.color = T.textDim)}
                  >
                    {it}
                  </a>
                ))}
              </div>
            ))}
          </div>

          <div
            style={{
              display: 'flex',
              justifyContent: 'space-between',
              alignItems: 'center',
              marginTop: 24,
              fontFamily: T.mono,
              fontSize: 10,
              letterSpacing: '0.22em',
              textTransform: 'uppercase',
              color: T.textFaint,
            }}
          >
            <span>© 2026 TheCee · Simulate before you build</span>
            <span>Set in Playfair & DM Sans · Filed in IST</span>
          </div>
        </div>
      </footer>

      <InlineAuth open={authOpen} onClose={() => setAuthOpen(false)} initialMode={authMode} />
    </div>
  )
}

/* ═════════════════════════════════════════════════════════════════
 *  Voice card
 * ═════════════════════════════════════════════════════════════════ */
function VoiceCard({
  bar, title, body, sig, role,
}: { bar: string; title: string; body: string; sig: string; role: string }) {
  const [hover, setHover] = useState(false)
  return (
    <motion.article
      onMouseEnter={() => setHover(true)}
      onMouseLeave={() => setHover(false)}
      whileHover={{ y: -4 }}
      transition={{ duration: 0.3, ease: [0.2, 0.7, 0.2, 1] }}
      style={{
        position: 'relative',
        padding: '36px 36px 30px',
        background: hover ? 'rgba(27,27,38,0.85)' : 'rgba(13,13,20,0.7)',
        border: `0.5px solid ${hover ? T.edgeHi : T.edge}`,
        borderLeft: `2px solid ${hover ? T.ember : T.edgeHi}`,
        transition: 'background 240ms ease, border-color 240ms ease',
        minHeight: 280,
        display: 'flex',
        flexDirection: 'column',
      }}
    >
      <div
        style={{
          fontFamily: T.mono,
          fontSize: 9,
          letterSpacing: '0.22em',
          textTransform: 'uppercase',
          color: T.ember,
          marginBottom: 22,
        }}
      >
        {bar}
      </div>
      <h3
        style={{
          fontFamily: T.serif,
          fontStyle: 'italic',
          fontWeight: 800,
          fontSize: 26,
          lineHeight: 1.2,
          letterSpacing: '-0.02em',
          color: T.text,
          marginBottom: 16,
        }}
      >
        &ldquo;{title}&rdquo;
      </h3>
      <p
        style={{
          fontSize: 15,
          lineHeight: 1.75,
          color: T.textDim,
          flex: 1,
        }}
      >
        {body}
      </p>
      <div
        style={{
          marginTop: 26,
          paddingTop: 18,
          borderTop: `0.5px solid ${T.edge}`,
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'center',
          fontFamily: T.mono,
          fontSize: 10,
          letterSpacing: '0.2em',
          textTransform: 'uppercase',
          color: T.textFaint,
        }}
      >
        <span>— {sig}</span>
        <span>{role}</span>
      </div>
    </motion.article>
  )
}

/* ═════════════════════════════════════════════════════════════════
 *  Tier card
 * ═════════════════════════════════════════════════════════════════ */
function TierCard({ tier, onClick }: { tier: typeof TIERS[number]; onClick: () => void }) {
  const [hover, setHover] = useState(false)
  const glow = tier.glow
  return (
    <motion.div
      onMouseEnter={() => setHover(true)}
      onMouseLeave={() => setHover(false)}
      whileHover={{ y: -6 }}
      transition={{ duration: 0.35, ease: [0.2, 0.7, 0.2, 1] }}
      style={{
        position: 'relative',
        padding: 40,
        background: glow
          ? `linear-gradient(180deg, rgba(255,106,61,0.08), rgba(13,13,20,0.9) 60%)`
          : 'rgba(13,13,20,0.75)',
        border: `0.5px solid ${glow ? T.ember : (hover ? T.edgeHi : T.edge)}`,
        boxShadow: glow
          ? `0 30px 80px rgba(255,106,61,0.18), 0 0 0 1px rgba(255,106,61,0.4)`
          : 'none',
        minHeight: 500,
        display: 'flex',
        flexDirection: 'column',
        overflow: 'hidden',
      }}
    >
      {glow && (
        <div
          aria-hidden
          style={{
            position: 'absolute',
            top: -80,
            right: -80,
            width: 260,
            height: 260,
            background: `radial-gradient(circle, rgba(255,106,61,0.25), transparent 70%)`,
            pointerEvents: 'none',
          }}
        />
      )}

      <div style={{ position: 'relative' }}>
        <div
          style={{
            fontFamily: T.mono,
            fontSize: 10,
            letterSpacing: '0.28em',
            textTransform: 'uppercase',
            color: T.ember,
            marginBottom: 16,
          }}
        >
          {tier.kicker}
        </div>
        <h3
          style={{
            fontFamily: T.serif,
            fontWeight: 900,
            fontStyle: 'italic',
            fontSize: 34,
            letterSpacing: '-0.03em',
            color: T.text,
            marginBottom: 20,
          }}
        >
          {tier.name}
        </h3>
        <div
          style={{
            fontFamily: T.serif,
            fontWeight: 900,
            fontSize: 64,
            letterSpacing: '-0.04em',
            lineHeight: 1,
            color: T.text,
            fontVariantNumeric: 'tabular-nums',
          }}
        >
          {tier.price}
        </div>
        <div
          style={{
            fontFamily: T.mono,
            fontSize: 10,
            letterSpacing: '0.22em',
            textTransform: 'uppercase',
            color: T.textFaint,
            marginTop: 8,
            marginBottom: 34,
          }}
        >
          {tier.sub}
        </div>

        <ul style={{ listStyle: 'none', padding: 0, margin: 0, flex: 1 }}>
          {tier.bullets.map(b => (
            <li
              key={b}
              style={{
                padding: '12px 0',
                borderBottom: `0.5px solid ${T.edge}`,
                fontSize: 13,
                color: T.textDim,
                display: 'flex',
                alignItems: 'center',
                gap: 12,
              }}
            >
              <Check size={13} color={glow ? T.ember : T.jade} />
              {b}
            </li>
          ))}
        </ul>

        <button
          type="button"
          onClick={onClick}
          style={{
            marginTop: 32,
            width: '100%',
            display: 'inline-flex',
            alignItems: 'center',
            justifyContent: 'center',
            gap: 10,
            padding: '16px 22px',
            background: glow ? T.ember : 'transparent',
            color: glow ? T.void : T.text,
            border: glow ? 'none' : `0.5px solid ${T.edgeHi}`,
            fontFamily: T.mono,
            fontSize: 11,
            letterSpacing: '0.22em',
            textTransform: 'uppercase',
            fontWeight: 700,
            cursor: 'pointer',
            transition: 'all 220ms ease',
          }}
          onMouseEnter={e => {
            if (glow) e.currentTarget.style.filter = 'brightness(1.08)'
            else { e.currentTarget.style.borderColor = T.ember; e.currentTarget.style.color = T.ember }
          }}
          onMouseLeave={e => {
            if (glow) e.currentTarget.style.filter = 'none'
            else { e.currentTarget.style.borderColor = T.edgeHi; e.currentTarget.style.color = T.text }
          }}
        >
          {tier.cta} <ArrowRight size={13} />
        </button>
      </div>
    </motion.div>
  )
}
