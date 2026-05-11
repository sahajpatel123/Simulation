'use client'

import React, { useRef, useState, useEffect } from 'react'
import { motion, useScroll, useTransform, useSpring, MotionValue } from 'framer-motion'
import Link from 'next/link'
import { ArrowRight, Activity, Crosshair, Database } from 'lucide-react'

import InlineAuth from '@/components/landing/InlineAuth'
import DossierSpecimen from '@/components/landing/DossierSpecimen'
import { useAuthStore } from '@/store/auth.store'
import { auth as authLib } from '@/lib/auth'

/* ─── MASTHEAD ──────────────────────────────────────────── */
function Masthead({
  setAuthOpen,
  setAuthMode,
  isAuthed,
  isHydrated,
}: {
  setAuthOpen: (o: boolean) => void
  setAuthMode: (m: 'login' | 'signup') => void
  isAuthed: boolean
  isHydrated: boolean
}) {
  const { scrollY } = useScroll()
  const bg = useTransform(scrollY, [0, 100], ['rgba(242,236,224,0)', 'rgba(242,236,224,0.85)'])
  const blur = useTransform(scrollY, [0, 100], ['blur(0px)', 'blur(16px)'])
  const border = useTransform(scrollY, [0, 100], ['0px solid rgba(26,23,20,0)', '0.5px solid rgba(26,23,20,0.08)'])

  return (
    <motion.header
      style={{
        position: 'fixed',
        top: 0,
        left: 0,
        right: 0,
        zIndex: 100,
        display: 'flex',
        justifyContent: 'space-between',
        alignItems: 'center',
        padding: '20px 48px',
        background: bg,
        backdropFilter: blur,
        WebkitBackdropFilter: blur,
        borderBottom: border,
      }}
    >
      <div className="font-serif" style={{ fontSize: 22, fontWeight: 900, fontStyle: 'italic', letterSpacing: '-0.02em', color: 'var(--ink)' }}>
        TheCee
      </div>
      <div style={{ display: 'flex', gap: 32, alignItems: 'center' }}>
        {isHydrated && isAuthed ? (
          <Link
            href="/projects"
            style={{
              fontSize: 10,
              color: 'var(--paper)',
              background: 'var(--ink)',
              padding: '12px 28px',
              textTransform: 'uppercase',
              letterSpacing: '0.15em',
              fontWeight: 800,
              textDecoration: 'none',
              borderRadius: 40,
              transition: 'transform 0.3s cubic-bezier(0.16, 1, 0.3, 1), box-shadow 0.3s ease',
              boxShadow: '0 8px 24px rgba(26,23,20,0.15)',
            }}
            onMouseEnter={e => { e.currentTarget.style.transform = 'translateY(-2px)'; e.currentTarget.style.boxShadow = '0 12px 32px rgba(26,23,20,0.2)' }}
            onMouseLeave={e => { e.currentTarget.style.transform = 'translateY(0)'; e.currentTarget.style.boxShadow = '0 8px 24px rgba(26,23,20,0.15)' }}
          >
            Enter Press
          </Link>
        ) : (
          <button
            onClick={() => {
              setAuthMode('login')
              setAuthOpen(true)
            }}
            style={{
              fontSize: 10,
              color: 'var(--ink)',
              background: 'none',
              border: 'none',
              textTransform: 'uppercase',
              letterSpacing: '0.15em',
              fontWeight: 800,
              cursor: 'pointer',
              position: 'relative',
            }}
          >
            Sign In
          </button>
        )}
      </div>
    </motion.header>
  )
}

/* ─── PREMIUM SCROLL HERO ──────────────────────────────────────────── */
function Hero() {
  const ref = useRef(null)
  const { scrollYProgress } = useScroll({ target: ref, offset: ['start start', 'end start'] })
  const y = useTransform(scrollYProgress, [0, 1], ['0%', '30%'])
  const opacity = useTransform(scrollYProgress, [0, 0.6], [1, 0])
  const blur = useTransform(scrollYProgress, [0, 0.8], ['blur(0px)', 'blur(20px)'])
  const scale = useTransform(scrollYProgress, [0, 1], [1, 0.95])

  return (
    <section ref={ref} style={{ height: '100vh', position: 'relative', display: 'flex', alignItems: 'center', justifyContent: 'center', background: 'var(--paper)', overflow: 'hidden' }}>
      {/* Subtle Grain Overlay for texture */}
      <div style={{ position: 'absolute', inset: 0, opacity: 0.4, backgroundImage: 'radial-gradient(var(--archive-grain-dot-a) 1px, transparent 1px)', backgroundSize: '32px 32px', pointerEvents: 'none' }} />

      <motion.div style={{ y, opacity, scale, filter: blur, WebkitFilter: blur, textAlign: 'center', zIndex: 10, padding: '0 40px' }}>
        <motion.div 
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 1.2, ease: [0.16, 1, 0.3, 1] }}
          style={{ fontSize: 11, letterSpacing: '0.3em', textTransform: 'uppercase', color: 'var(--red)', fontWeight: 800, marginBottom: 40 }}
        >
          The Behavioral Simulation Engine
        </motion.div>
        
        <h1 className="font-serif" style={{ fontSize: 'clamp(60px, 10vw, 150px)', fontWeight: 900, color: 'var(--ink)', lineHeight: 0.9, letterSpacing: '-0.04em' }}>
          <motion.span initial={{ opacity: 0, y: 30, filter: 'blur(10px)' }} animate={{ opacity: 1, y: 0, filter: 'blur(0px)' }} transition={{ duration: 1.4, delay: 0.1, ease: [0.16, 1, 0.3, 1] }} style={{ display: 'inline-block' }}>
            Stop guessing.
          </motion.span>
          <br />
          <motion.span initial={{ opacity: 0, y: 30, filter: 'blur(10px)' }} animate={{ opacity: 1, y: 0, filter: 'blur(0px)' }} transition={{ duration: 1.4, delay: 0.3, ease: [0.16, 1, 0.3, 1] }} style={{ display: 'inline-block', fontStyle: 'italic', color: 'var(--ink-secondary)' }}>
            Start simulating.
          </motion.span>
        </h1>

        <motion.div
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          transition={{ duration: 2, delay: 1 }}
          style={{ position: 'absolute', bottom: -120, left: '50%', transform: 'translateX(-50%)', width: 1, height: 80, background: 'linear-gradient(to bottom, var(--ink), transparent)' }}
        />
      </motion.div>
    </section>
  )
}

/* ─── NARRATIVE SCROLL (REFINED, CENTERED, READABLE) ──────────────────────────────────────────── */
function NarrativeScroll() {
  const ref = React.useRef(null)
  const { scrollYProgress } = useScroll({ target: ref, offset: ['start start', 'end end'] })

  // We spread the timeline out more safely so text doesn't overlap or blur out constantly.
  // Slide 1 (0.0 to 0.3)
  const o1 = useTransform(scrollYProgress, [0, 0.05, 0.25, 0.3], [0, 1, 1, 0])
  const y1 = useTransform(scrollYProgress, [0, 0.05, 0.25, 0.3], [40, 0, 0, -40])
  const b1 = useTransform(scrollYProgress, [0, 0.05, 0.25, 0.3], ['blur(10px)', 'blur(0px)', 'blur(0px)', 'blur(10px)'])

  // Slide 2 (0.35 to 0.65)
  const o2 = useTransform(scrollYProgress, [0.35, 0.4, 0.6, 0.65], [0, 1, 1, 0])
  const y2 = useTransform(scrollYProgress, [0.35, 0.4, 0.6, 0.65], [40, 0, 0, -40])
  const b2 = useTransform(scrollYProgress, [0.35, 0.4, 0.6, 0.65], ['blur(10px)', 'blur(0px)', 'blur(0px)', 'blur(10px)'])

  // Slide 3 (0.7 to 1.0)
  const o3 = useTransform(scrollYProgress, [0.7, 0.75, 0.95, 1], [0, 1, 1, 0])
  const y3 = useTransform(scrollYProgress, [0.7, 0.75, 0.95, 1], [40, 0, 0, -40])
  const b3 = useTransform(scrollYProgress, [0.7, 0.75, 0.95, 1], ['blur(10px)', 'blur(0px)', 'blur(0px)', 'blur(10px)'])

  const textStyle: React.CSSProperties = {
    position: 'absolute',
    top: 0, left: 0, right: 0, bottom: 0,
    display: 'flex',
    flexDirection: 'column',
    alignItems: 'center',
    justifyContent: 'center',
    textAlign: 'center',
    fontSize: 'clamp(32px, 5vw, 72px)',
    fontFamily: 'var(--font-serif)',
    fontWeight: 500,
    color: 'var(--paper)',
    lineHeight: 1.1,
    letterSpacing: '-0.02em',
    padding: '0 5%',
  }

  return (
    <section ref={ref} style={{ height: '400vh', background: '#050505', position: 'relative' }}>
      <div style={{ position: 'sticky', top: 0, height: '100vh', overflow: 'hidden' }}>
        
        <motion.div style={{ ...textStyle, opacity: o1, y: y1, filter: b1, WebkitFilter: b1 }}>
          <p style={{ margin: 0, maxWidth: 1000 }}>
            You have an idea.<br />You build it for six months.<br />
            <span style={{ color: 'var(--red)', fontStyle: 'italic' }}>Then you find out nobody wants it.</span>
          </p>
        </motion.div>

        <motion.div style={{ ...textStyle, opacity: o2, y: y2, filter: b2, WebkitFilter: b2 }}>
          <p style={{ margin: 0, maxWidth: 1000 }}>
            What if you could put <br />your idea in front of <br />
            <span style={{ fontStyle: 'italic' }}>10,000 synthetic readers</span> today?
          </p>
        </motion.div>

        <motion.div style={{ ...textStyle, opacity: o3, y: y3, filter: b3, WebkitFilter: b3 }}>
          <p style={{ margin: 0, maxWidth: 1000 }}>
            We print the autopsy<br />before the burial.<br />
            <span style={{ color: 'var(--red)', fontStyle: 'italic' }}>In exactly two minutes.</span>
          </p>
        </motion.div>
        
      </div>
    </section>
  )
}

/* ─── THE DIRECTIVE (SYMMETRICAL GLASS SPREAD) ──────────────────────────────────────────── */
function DirectiveFeatures() {
  const ref = React.useRef(null)
  const { scrollYProgress } = useScroll({ target: ref, offset: ['start start', 'end end'] })

  // Spread animations
  // Progress 0.1 to 0.4: Fanning out
  const spreadProgress = useTransform(scrollYProgress, [0.1, 0.5], [0, 1])

  const leftX = useTransform(spreadProgress, [0, 1], [0, -380])
  const leftRotate = useTransform(spreadProgress, [0, 1], [0, -8])
  const leftY = useTransform(spreadProgress, [0, 1], [0, 40])

  const rightX = useTransform(spreadProgress, [0, 1], [0, 380])
  const rightRotate = useTransform(spreadProgress, [0, 1], [0, 8])
  const rightY = useTransform(spreadProgress, [0, 1], [0, 40])

  const centerScale = useTransform(spreadProgress, [0, 1], [0.95, 1.05])
  const centerY = useTransform(spreadProgress, [0, 1], [0, -20])

  const textOpacity = useTransform(scrollYProgress, [0, 0.05], [1, 1]) // Forced to 1 for full visibility
  const headerY = useTransform(scrollYProgress, [0, 0.05], [20, 0])

  const cardShadow = useTransform(
    spreadProgress,
    [0, 1],
    ['0 10px 30px rgba(0,0,0,0.05)', '0 40px 80px rgba(0,0,0,0.12)']
  )

  const detailsOpacity = useTransform(scrollYProgress, [0.4, 0.6], [0, 1])

  return (
    <section ref={ref} style={{ height: '300vh', background: '#f9f8f6', position: 'relative' }}>
      <div style={{ position: 'sticky', top: 0, height: '100vh', display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', overflow: 'hidden' }}>
        
        {/* Header */}
        <motion.div style={{ opacity: textOpacity, y: headerY, textAlign: 'center', position: 'absolute', top: '12%', zIndex: 10 }}>
          <div style={{ fontSize: 11, letterSpacing: '0.3em', textTransform: 'uppercase', color: 'var(--red)', fontWeight: 800, marginBottom: 16 }}>
            The Output
          </div>
          <h2 className="font-serif" style={{ fontSize: 'clamp(40px, 6vw, 80px)', fontWeight: 900, color: 'var(--ink)', letterSpacing: '-0.03em', lineHeight: 1 }}>
            A clear <span style={{ color: 'var(--red)', fontStyle: 'italic' }}>directive.</span>
          </h2>
        </motion.div>

        {/* The Deck of Cards */}
        <div style={{ position: 'relative', width: 340, height: 460, marginTop: '5%' }}>
          
          {/* Card 1: Left (Validation) */}
          <motion.div 
            style={{ 
              position: 'absolute', inset: 0, x: leftX, y: leftY, rotate: leftRotate, 
              background: 'var(--paper)', borderRadius: 24, padding: 40,
              boxShadow: cardShadow, border: '0.5px solid rgba(0,0,0,0.08)',
              display: 'flex', flexDirection: 'column', zIndex: 1
            }}
          >
            <div style={{ padding: 12, background: 'rgba(192,57,43,0.1)', borderRadius: 12, color: 'var(--red)', display: 'inline-block', width: 'fit-content', marginBottom: 24 }}>
              <Database size={24} />
            </div>
            <h3 className="font-serif" style={{ fontSize: 32, fontWeight: 900, marginBottom: 16, lineHeight: 1.1, letterSpacing: '-0.02em', color: 'var(--ink)' }}>
              Targeted<br/>Validation.
            </h3>
            <motion.div style={{ opacity: detailsOpacity, flex: 1, display: 'flex', flexDirection: 'column', justifyContent: 'flex-end' }}>
              <p style={{ fontSize: 14, color: 'var(--ink-secondary)', lineHeight: 1.6, fontWeight: 500, margin: 0 }}>
                Tested across 52 distinct behavioral clusters instantly. Real willingness to pay.
              </p>
            </motion.div>
          </motion.div>

          {/* Card 3: Right (Pre-Mortem) */}
          <motion.div 
            style={{ 
              position: 'absolute', inset: 0, x: rightX, y: rightY, rotate: rightRotate, 
              background: 'var(--paper)', borderRadius: 24, padding: 40,
              boxShadow: cardShadow, border: '0.5px solid rgba(0,0,0,0.08)',
              display: 'flex', flexDirection: 'column', zIndex: 1
            }}
          >
            <div style={{ padding: 12, background: 'rgba(192,57,43,0.1)', borderRadius: 12, color: 'var(--red)', display: 'inline-block', width: 'fit-content', marginBottom: 24 }}>
              <Activity size={24} />
            </div>
            <h3 className="font-serif" style={{ fontSize: 32, fontWeight: 900, marginBottom: 16, lineHeight: 1.1, letterSpacing: '-0.02em', color: 'var(--ink)' }}>
              The<br/>Pre-Mortem.
            </h3>
            <motion.div style={{ opacity: detailsOpacity, flex: 1, display: 'flex', flexDirection: 'column', justifyContent: 'flex-end' }}>
              <p style={{ fontSize: 14, color: 'var(--ink-secondary)', lineHeight: 1.6, fontWeight: 500, margin: 0 }}>
                Structural failure modes exposed. Fix the vital flaws before they become code.
              </p>
            </motion.div>
          </motion.div>

          {/* Card 2: Center (Channel Fit) - Highest Z-Index */}
          <motion.div 
            style={{ 
              position: 'absolute', inset: 0, scale: centerScale, y: centerY,
              background: 'var(--ink)', color: 'var(--paper)', borderRadius: 24, padding: 40,
              boxShadow: cardShadow, border: '0.5px solid rgba(255,255,255,0.15)',
              display: 'flex', flexDirection: 'column', zIndex: 10
            }}
          >
            <div style={{ padding: 12, background: 'rgba(255,255,255,0.1)', borderRadius: 12, color: '#fff', display: 'inline-block', width: 'fit-content', marginBottom: 24 }}>
              <Crosshair size={24} />
            </div>
            <h3 className="font-serif" style={{ fontSize: 36, fontWeight: 900, marginBottom: 16, lineHeight: 1.1, letterSpacing: '-0.02em' }}>
              Absolute<br/>Channel Fit.
            </h3>
            <motion.div style={{ opacity: detailsOpacity, flex: 1, display: 'flex', flexDirection: 'column', justifyContent: 'flex-end' }}>
              <div style={{ height: 4, background: 'rgba(255,255,255,0.1)', borderRadius: 2, overflow: 'hidden', marginBottom: 16 }}>
                <div style={{ width: '85%', height: '100%', background: 'var(--red)' }} />
              </div>
              <p style={{ fontSize: 14, color: 'rgba(255,255,255,0.7)', lineHeight: 1.6, fontWeight: 500, margin: 0 }}>
                <span style={{ color: '#fff', fontWeight: 800 }}>85% conversion</span> probability on visual networks. Traced instantly.
              </p>
            </motion.div>
          </motion.div>

        </div>

      </div>
    </section>
  )
}

/* ─── THE DISTRIBUTION (PREMIUM SCROLL BAR CHART) ──────────────────────────────────────────── */
function DistributionRow({
  d,
  i,
  scrollYProgress,
}: {
  d: { label: string; sub: string; pct: number; color: string }
  i: number
  scrollYProgress: MotionValue<number>
}) {
  const start = 0.1 + i * 0.1
  const end = 0.4 + i * 0.1
  const width = useTransform(scrollYProgress, [start, end], ['0%', `${d.pct}%`])
  const opacity = useTransform(scrollYProgress, [start, end], [0, 1])
  const y = useTransform(scrollYProgress, [start, end], [20, 0])

  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 60, padding: '24px 0', borderBottom: '0.5px solid rgba(26,23,20,0.05)' }}>
      <div style={{ width: 240 }}>
        <div style={{ fontSize: 13, fontWeight: 800, textTransform: 'uppercase', letterSpacing: '0.15em', color: d.color }}>
          {d.label}
        </div>
        <div style={{ fontSize: 12, color: 'var(--ink-secondary)', marginTop: 8, fontWeight: 500 }}>{d.sub}</div>
      </div>
      <div style={{ flex: 1, position: 'relative', height: 16 }}>
        <div style={{ position: 'absolute', top: '50%', transform: 'translateY(-50%)', left: 0, right: 0, height: 1, background: 'rgba(26,23,20,0.08)' }} />
        <motion.div style={{ position: 'absolute', top: 0, bottom: 0, left: 0, background: d.color, width, borderRadius: 8, boxShadow: `0 4px 12px ${d.color}33` }} />
      </div>
      <motion.div style={{ opacity, y, width: 100, textAlign: 'right', fontSize: 48, fontWeight: 900, fontFamily: 'var(--font-serif)', color: d.color, fontStyle: 'italic', letterSpacing: '-0.02em' }}>
        {d.pct}<span style={{ fontSize: 24, opacity: 0.5 }}>%</span>
      </motion.div>
    </div>
  )
}

function Distribution() {
  const ref = useRef(null)
  const { scrollYProgress } = useScroll({ target: ref, offset: ['start center', 'end center'] })

  const data = [
    { label: 'Dies fast', sub: 'runway gone in 90 days', pct: 14, color: 'var(--ink)' },
    { label: 'Quiet death', sub: 'grows, then stalls', pct: 23, color: '#5a4e42' },
    { label: 'Pivots', sub: 'idea survives, shape changes', pct: 31, color: 'var(--red)' },
    { label: 'Survives', sub: 'modest, compounding', pct: 22, color: '#786e48' },
    { label: 'Scales', sub: 'the bet you are making', pct: 10, color: '#3a5a48' },
  ]

  return (
    <section ref={ref} style={{ padding: '160px clamp(48px, 6vw, 80px)', background: 'var(--paper)', maxWidth: 1100, margin: '0 auto' }}>
      <div style={{ textAlign: 'center', marginBottom: 140 }}>
        <div style={{ fontSize: 11, letterSpacing: '0.2em', textTransform: 'uppercase', color: 'var(--ink-secondary)', fontWeight: 800, marginBottom: 16 }}>
          The Futures
        </div>
        <h2 className="font-serif" style={{ fontSize: 'clamp(40px, 6vw, 88px)', fontWeight: 900, letterSpacing: '-0.03em', color: 'var(--ink)', lineHeight: 1.05 }}>
          Every idea has a shape.<br />
          <span style={{ fontStyle: 'italic', color: 'var(--red)' }}>We show you yours.</span>
        </h2>
      </div>

      <div style={{ display: 'flex', flexDirection: 'column' }}>
        {data.map((d, i) => (
          <DistributionRow key={d.label} d={d} i={i} scrollYProgress={scrollYProgress} />
        ))}
      </div>
    </section>
  )
}

/* ─── FOOTER ──────────────────────────────────────────── */
function FooterSection() {
  return (
    <footer style={{ background: '#050505', padding: '120px 64px', color: 'var(--paper)', borderTop: '1px solid rgba(255,255,255,0.1)' }}>
      <div style={{ maxWidth: 1400, margin: '0 auto', width: '100%', display: 'flex', justifyContent: 'space-between', alignItems: 'flex-end', flexWrap: 'wrap', gap: 40 }}>
        <div>
          <h2 className="font-serif" style={{ fontSize: 56, fontWeight: 900, fontStyle: 'italic', letterSpacing: '-0.02em', marginBottom: 24 }}>
            TheCee
          </h2>
          <div style={{ fontSize: 15, color: 'rgba(255,255,255,0.4)', maxWidth: 360, lineHeight: 1.6, fontWeight: 400 }}>
            The simulation broadsheet. Filed quarterly, on the Internet, since 2026.
          </div>
        </div>
        <div style={{ textAlign: 'right' }}>
          <div style={{ display: 'flex', gap: 40, marginBottom: 40, fontSize: 12, letterSpacing: '0.15em', textTransform: 'uppercase', color: 'rgba(255,255,255,0.8)', fontWeight: 600 }}>
            <a href="#" style={{ color: 'inherit', textDecoration: 'none' }}>About</a>
            <a href="#" style={{ color: 'inherit', textDecoration: 'none' }}>Methodology</a>
            <a href="#" style={{ color: 'inherit', textDecoration: 'none' }}>Press</a>
          </div>
          <div style={{ fontSize: 10, letterSpacing: '0.2em', textTransform: 'uppercase', color: 'rgba(255,255,255,0.3)', fontWeight: 700 }}>
            © 2026 TheCee — Printed in IST
          </div>
        </div>
      </div>
    </footer>
  )
}

/* ─── MAIN APP ──────────────────────────────────────────── */
export default function LandingPage() {
  const [authOpen, setAuthOpen] = useState(false)
  const [authMode, setAuthMode] = useState<'login' | 'signup'>('login')

  const user = useAuthStore((s) => s.user)
  const isHydrated = useAuthStore((s) => s.isHydrated)
  const isAuthed = Boolean(user) || (isHydrated && typeof window !== 'undefined' && authLib.isAuthenticated())

  return (
    <div style={{ background: 'var(--paper)', minHeight: '100vh' }}>
      <Masthead setAuthOpen={setAuthOpen} setAuthMode={setAuthMode} isAuthed={isAuthed} isHydrated={isHydrated} />
      <Hero />
      <NarrativeScroll />
      <DirectiveFeatures />
      <Distribution />
      <FooterSection />
      <InlineAuth open={authOpen} onClose={() => setAuthOpen(false)} initialMode={authMode} />
    </div>
  )
}
