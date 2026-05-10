'use client'

import React, { useRef, useState } from 'react'
import { motion, useScroll, useTransform, MotionValue } from 'framer-motion'
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
  const bg = useTransform(scrollY, [0, 100], ['rgba(242,236,224,0)', 'rgba(242,236,224,0.9)'])
  const blur = useTransform(scrollY, [0, 100], ['blur(0px)', 'blur(10px)'])
  const border = useTransform(scrollY, [0, 100], ['0px solid rgba(0,0,0,0)', '1px solid rgba(0,0,0,0.1)'])

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
        padding: '24px 48px',
        background: bg,
        backdropFilter: blur,
        WebkitBackdropFilter: blur,
        borderBottom: border,
      }}
    >
      <div className="font-serif" style={{ fontSize: 24, fontWeight: 900, fontStyle: 'italic', letterSpacing: '-0.02em', color: 'var(--ink)' }}>
        TheCee
      </div>
      <div style={{ display: 'flex', gap: 24, alignItems: 'center' }}>
        {isHydrated && isAuthed ? (
          <Link
            href="/projects"
            style={{
              fontSize: 11,
              color: 'var(--paper)',
              background: 'var(--ink)',
              padding: '10px 24px',
              textTransform: 'uppercase',
              letterSpacing: '0.1em',
              fontWeight: 700,
              textDecoration: 'none',
              borderRadius: 40,
            }}
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
              fontSize: 11,
              color: 'var(--ink)',
              background: 'none',
              border: 'none',
              textTransform: 'uppercase',
              letterSpacing: '0.1em',
              fontWeight: 700,
              cursor: 'pointer',
            }}
          >
            Sign In
          </button>
        )}
      </div>
    </motion.header>
  )
}

/* ─── SCROLL HERO ──────────────────────────────────────────── */
function Hero() {
  const ref = useRef(null)
  const { scrollYProgress } = useScroll({ target: ref, offset: ['start start', 'end start'] })
  const y = useTransform(scrollYProgress, [0, 1], ['0%', '40%'])
  const opacity = useTransform(scrollYProgress, [0, 0.8], [1, 0])
  const scale = useTransform(scrollYProgress, [0, 1], [1, 0.9])

  return (
    <section ref={ref} style={{ height: '100vh', position: 'relative', display: 'flex', alignItems: 'center', justifyContent: 'center', background: 'var(--paper)', overflow: 'hidden' }}>
      <motion.div style={{ y, opacity, scale, textAlign: 'center', zIndex: 10, padding: '0 40px' }}>
        <div style={{ fontSize: 12, letterSpacing: '0.3em', textTransform: 'uppercase', color: 'var(--red)', fontWeight: 800, marginBottom: 40 }}>
          The Behavioral Simulation Engine
        </div>
        <h1 className="font-serif" style={{ fontSize: 'clamp(60px, 10vw, 160px)', fontWeight: 900, color: 'var(--ink)', lineHeight: 0.9, letterSpacing: '-0.04em' }}>
          Stop guessing.<br />
          <span style={{ fontStyle: 'italic', color: 'var(--ink-secondary)' }}>Start simulating.</span>
        </h1>
      </motion.div>
    </section>
  )
}

/* ─── NARRATIVE SCROLL ──────────────────────────────────────────── */
function NarrativeScroll() {
  const ref = useRef(null)
  const { scrollYProgress } = useScroll({ target: ref, offset: ['start start', 'end end'] })

  const o1 = useTransform(scrollYProgress, [0, 0.15, 0.25, 0.35], [0, 1, 1, 0])
  const y1 = useTransform(scrollYProgress, [0, 0.15, 0.25, 0.35], [40, 0, 0, -40])

  const o2 = useTransform(scrollYProgress, [0.35, 0.45, 0.55, 0.65], [0, 1, 1, 0])
  const y2 = useTransform(scrollYProgress, [0.35, 0.45, 0.55, 0.65], [40, 0, 0, -40])

  const o3 = useTransform(scrollYProgress, [0.65, 0.75, 0.85, 1], [0, 1, 1, 0])
  const y3 = useTransform(scrollYProgress, [0.65, 0.75, 0.85, 1], [40, 0, 0, -40])

  const textStyle: React.CSSProperties = {
    position: 'absolute',
    top: '50%',
    left: '50%',
    transform: 'translate(-50%, -50%)',
    width: '100%',
    maxWidth: 1000,
    textAlign: 'center',
    fontSize: 'clamp(32px, 5vw, 64px)',
    fontFamily: 'var(--font-serif)',
    fontWeight: 500,
    color: 'var(--paper)',
    lineHeight: 1.1,
    letterSpacing: '-0.02em',
  }

  return (
    <section ref={ref} style={{ height: '400vh', background: 'var(--ink)', position: 'relative' }}>
      <div style={{ position: 'sticky', top: 0, height: '100vh', display: 'flex', alignItems: 'center', justifyContent: 'center', overflow: 'hidden' }}>
        <motion.div style={{ ...textStyle, opacity: o1, y: y1 }}>
          You have an idea.<br />You build it for six months.<br />
          <span style={{ color: 'var(--red)', fontStyle: 'italic' }}>Then you find out nobody wants it.</span>
        </motion.div>

        <motion.div style={{ ...textStyle, opacity: o2, y: y2 }}>
          What if you could put <br />your idea in front of <br />
          <span style={{ fontStyle: 'italic' }}>10,000 synthetic readers</span> today?
        </motion.div>

        <motion.div style={{ ...textStyle, opacity: o3, y: y3 }}>
          We print the autopsy<br />before the burial.<br />
          <span style={{ color: 'var(--red)', fontStyle: 'italic' }}>In exactly two minutes.</span>
        </motion.div>
      </div>
    </section>
  )
}

/* ─── THE ANATOMY (SCROLL-JACKED DOSSIER) ──────────────────────────────────────────── */
function Anatomy() {
  const ref = useRef(null)
  const { scrollYProgress } = useScroll({ target: ref, offset: ['start start', 'end end'] })

  const scale = useTransform(scrollYProgress, [0, 0.2], [0.8, 1])
  const opacity = useTransform(scrollYProgress, [0, 0.2], [0, 1])

  const a1 = useTransform(scrollYProgress, [0.2, 0.3], [0, 1])
  const a2 = useTransform(scrollYProgress, [0.4, 0.5], [0, 1])
  const a3 = useTransform(scrollYProgress, [0.6, 0.7], [0, 1])

  return (
    <section ref={ref} style={{ height: '300vh', background: 'var(--paper-dark)', position: 'relative' }}>
      <div style={{ position: 'sticky', top: 0, height: '100vh', display: 'flex', alignItems: 'center', justifyContent: 'center', overflow: 'hidden' }}>
        <div style={{ position: 'absolute', top: '10%', textAlign: 'center', zIndex: 10 }}>
          <div style={{ fontSize: 11, letterSpacing: '0.2em', textTransform: 'uppercase', color: 'var(--ink-secondary)', fontWeight: 800, marginBottom: 12 }}>
            The Specimen
          </div>
          <h2 className="font-serif" style={{ fontSize: 'clamp(32px, 4vw, 48px)', fontWeight: 900, color: 'var(--ink)', letterSpacing: '-0.02em' }}>
            The output is a clear directive.
          </h2>
        </div>

        <motion.div style={{ scale, opacity, width: '100%', maxWidth: 1000, position: 'relative' }}>
          <div style={{ pointerEvents: 'none' }}>
            <DossierSpecimen />
          </div>

          <motion.div style={{ opacity: a1, position: 'absolute', top: '10%', left: '-15%', background: 'var(--paper)', padding: 24, border: '1px solid var(--border-color)', boxShadow: '0 20px 40px rgba(0,0,0,0.05)', width: 280, borderRadius: 12 }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 10 }}>
              <div style={{ padding: 8, background: 'rgba(192,57,43,0.1)', borderRadius: 8, color: 'var(--red)' }}>
                <Database size={16} />
              </div>
              <div style={{ fontSize: 10, textTransform: 'uppercase', letterSpacing: '0.1em', fontWeight: 800 }}>Validation</div>
            </div>
            <div style={{ fontSize: 14, color: 'var(--ink-secondary)', lineHeight: 1.5 }}>
              Tests willingness to pay across 52 behavioral clusters instantly.
            </div>
          </motion.div>

          <motion.div style={{ opacity: a2, position: 'absolute', top: '45%', right: '-15%', background: 'var(--paper)', padding: 24, border: '1px solid var(--border-color)', boxShadow: '0 20px 40px rgba(0,0,0,0.05)', width: 280, borderRadius: 12 }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 10 }}>
              <div style={{ padding: 8, background: 'rgba(192,57,43,0.1)', borderRadius: 8, color: 'var(--red)' }}>
                <Crosshair size={16} />
              </div>
              <div style={{ fontSize: 10, textTransform: 'uppercase', letterSpacing: '0.1em', fontWeight: 800 }}>Channel Fit</div>
            </div>
            <div style={{ fontSize: 14, color: 'var(--ink-secondary)', lineHeight: 1.5 }}>
              Identifies exactly where your audience lives, clicks, and buys.
            </div>
          </motion.div>

          <motion.div style={{ opacity: a3, position: 'absolute', bottom: '15%', left: '-10%', background: 'var(--paper)', padding: 24, border: '1px solid var(--border-color)', boxShadow: '0 20px 40px rgba(0,0,0,0.05)', width: 280, borderRadius: 12 }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 10 }}>
              <div style={{ padding: 8, background: 'rgba(192,57,43,0.1)', borderRadius: 8, color: 'var(--red)' }}>
                <Activity size={16} />
              </div>
              <div style={{ fontSize: 10, textTransform: 'uppercase', letterSpacing: '0.1em', fontWeight: 800 }}>Pre-mortem</div>
            </div>
            <div style={{ fontSize: 14, color: 'var(--ink-secondary)', lineHeight: 1.5 }}>
              Exposes the exact structural reasons your product will fail.
            </div>
          </motion.div>
        </motion.div>
      </div>
    </section>
  )
}

/* ─── THE DISTRIBUTION (SCROLL BAR CHART) ──────────────────────────────────────────── */
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

  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 40 }}>
      <div style={{ width: 200 }}>
        <div style={{ fontSize: 14, fontWeight: 800, textTransform: 'uppercase', letterSpacing: '0.15em', color: d.color }}>
          {d.label}
        </div>
        <div style={{ fontSize: 12, color: 'var(--ink-secondary)', marginTop: 4 }}>{d.sub}</div>
      </div>
      <div style={{ flex: 1, position: 'relative', height: 40 }}>
        <div style={{ position: 'absolute', top: '50%', transform: 'translateY(-50%)', left: 0, right: 0, height: 2, background: 'var(--border-color)' }} />
        <motion.div style={{ position: 'absolute', top: 0, bottom: 0, left: 0, background: d.color, width, borderRadius: 4 }} />
      </div>
      <motion.div style={{ opacity, width: 80, textAlign: 'right', fontSize: 40, fontWeight: 900, fontFamily: 'var(--font-serif)', color: d.color, fontStyle: 'italic' }}>
        {d.pct}%
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
    <section ref={ref} style={{ padding: '200px 48px', background: 'var(--paper)', maxWidth: 1000, margin: '0 auto' }}>
      <div style={{ textAlign: 'center', marginBottom: 120 }}>
        <h2 className="font-serif" style={{ fontSize: 'clamp(40px, 6vw, 80px)', fontWeight: 900, letterSpacing: '-0.02em', color: 'var(--ink)', lineHeight: 1.1 }}>
          Every idea has a shape.<br />
          <span style={{ fontStyle: 'italic', color: 'var(--red)' }}>We show you yours.</span>
        </h2>
      </div>

      <div style={{ display: 'flex', flexDirection: 'column', gap: 40 }}>
        {data.map((d, i) => (
          <DistributionRow key={d.label} d={d} i={i} scrollYProgress={scrollYProgress} />
        ))}
      </div>
    </section>
  )
}

/* ─── TIERS & FINAL CTA ──────────────────────────────────────────── */
function SubscriptionsAndCTA({
  setAuthMode,
  setAuthOpen,
}: {
  setAuthMode: (m: 'login' | 'signup') => void
  setAuthOpen: (o: boolean) => void
}) {
  const TIERS = [
    { name: 'Single Issue', price: 'Free', sub: 'Forever', bullets: ['1 active dossier', '500 simulated readers', 'Pre-mortem report'], cta: 'Run your first' },
    { name: 'Quarterly', price: '₹1,200', sub: 'Per month', bullets: ['10 active dossiers', '10,000 readers', 'Decision Studio', 'Cross-validation'], cta: 'Open a quarterly' },
  ]

  return (
    <section style={{ borderTop: '1px solid var(--border-color)' }}>
      {/* Tiers */}
      <div style={{ display: 'flex', flexWrap: 'wrap' }}>
        {TIERS.map((t, i) => (
          <div key={t.name} style={{ flex: 1, minWidth: 300, padding: '120px 80px', borderRight: i === 0 ? '1px solid var(--border-color)' : 'none', background: i === 1 ? 'var(--ink)' : 'var(--paper)', color: i === 1 ? 'var(--paper)' : 'var(--ink)' }}>
            <h3 className="font-serif" style={{ fontSize: 32, fontWeight: 900, fontStyle: 'italic', marginBottom: 20 }}>
              {t.name}
            </h3>
            <div className="font-serif" style={{ fontSize: 64, fontWeight: 900, letterSpacing: '-0.04em', lineHeight: 1 }}>
              {t.price}
            </div>
            <div style={{ fontSize: 12, letterSpacing: '0.2em', textTransform: 'uppercase', opacity: 0.6, marginTop: 10, marginBottom: 40, fontWeight: 800 }}>
              {t.sub}
            </div>
            <ul style={{ listStyle: 'none', padding: 0, margin: 0, marginBottom: 60 }}>
              {t.bullets.map((b) => (
                <li key={b} style={{ padding: '16px 0', borderBottom: `1px solid ${i === 1 ? 'rgba(255,255,255,0.1)' : 'var(--border-color)'}`, fontSize: 14, display: 'flex', alignItems: 'center', gap: 12 }}>
                  <div style={{ width: 6, height: 6, borderRadius: '50%', background: 'var(--red)' }} /> {b}
                </li>
              ))}
            </ul>
            <button
              onClick={() => {
                setAuthMode('signup')
                setAuthOpen(true)
              }}
              style={{
                padding: '20px 40px',
                width: '100%',
                background: i === 1 ? 'var(--red)' : 'var(--ink)',
                color: 'var(--paper)',
                border: 'none',
                borderRadius: 8,
                fontSize: 12,
                letterSpacing: '0.2em',
                textTransform: 'uppercase',
                fontWeight: 800,
                cursor: 'pointer',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                gap: 12,
              }}
            >
              {t.cta} <ArrowRight size={16} />
            </button>
          </div>
        ))}
      </div>

      {/* Footer */}
      <footer style={{ background: '#0a0a0a', padding: '100px 48px', color: 'var(--paper)' }}>
        <div style={{ maxWidth: 1200, margin: '0 auto', display: 'flex', justifyContent: 'space-between', alignItems: 'flex-end' }}>
          <div>
            <h2 className="font-serif" style={{ fontSize: 48, fontWeight: 900, fontStyle: 'italic', letterSpacing: '-0.02em', marginBottom: 20 }}>
              TheCee
            </h2>
            <div style={{ fontSize: 14, color: 'rgba(255,255,255,0.5)', maxWidth: 300, lineHeight: 1.6 }}>
              The simulation broadsheet. Filed quarterly, on the Internet, since 2026.
            </div>
          </div>
          <div style={{ fontSize: 11, letterSpacing: '0.2em', textTransform: 'uppercase', color: 'rgba(255,255,255,0.3)', fontWeight: 700 }}>
            © 2026 TheCee — Set in Playfair & DM Sans
          </div>
        </div>
      </footer>
    </section>
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
      <Anatomy />
      <Distribution />
      <SubscriptionsAndCTA setAuthMode={setAuthMode} setAuthOpen={setAuthOpen} />
      <InlineAuth open={authOpen} onClose={() => setAuthOpen(false)} initialMode={authMode} />
    </div>
  )
}
