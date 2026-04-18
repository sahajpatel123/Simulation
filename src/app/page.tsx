'use client'

import { useEffect, useRef, useState } from 'react'
import { motion, useScroll, useTransform, AnimatePresence } from 'framer-motion'
import Link from 'next/link'
import { ArrowRight, ArrowUpRight, ChevronDown, Minus } from 'lucide-react'

import FeatureShowcase from '@/components/layout/FeatureShowcase'
import SimulationTimeline from '@/components/layout/SimulationTimeline'
import InkCursor from '@/components/landing/InkCursor'
import TypesetHeadline from '@/components/landing/TypesetHeadline'
import MagneticCTA from '@/components/landing/MagneticCTA'
import PressTicker from '@/components/landing/PressTicker'
import LiveCounters from '@/components/landing/LiveCounters'
import DossierSpecimen from '@/components/landing/DossierSpecimen'
import InlineAuth from '@/components/landing/InlineAuth'

import { useAuthStore } from '@/store/auth.store'
import { auth as authLib } from '@/lib/auth'
import { useLogout } from '@/hooks/useAuth'

/* ─── COPY ──────────────────────────────────────────── */
const ROTATING = ['startup', 'product', 'idea', 'launch', 'pricing', 'pivot']

const PLATES = [
  {
    n: 'I',
    kicker: 'Set the type',
    title: 'Write the idea, in your handwriting',
    body:
      'Plain words on a clean page. No frameworks, no templates. Drop the assumption you are afraid to put on paper — that is the one we are going to test first.',
  },
  {
    n: 'II',
    kicker: 'Run the press',
    title: 'Send it under thousands of synthetic readers',
    body:
      'Cast assembled, scenarios laid out, the room goes quiet. Your idea runs against markets that do not flatter it — pricing, channel, timing, defection, the lot.',
  },
  {
    n: 'III',
    kicker: 'File the report',
    title: 'Read the autopsy before you spend a rupee',
    body:
      'Failure modes ranked. Surviving paths drawn. The exact interventions that shift the odds, on the desk in under two minutes.',
  },
] as const

const LETTERS = [
  {
    title: 'First-time founders',
    body: 'You are launching your first product with limited runway. Run it through the press before you spend it.',
    sig: 'Field, Bangalore',
    tag: 'Validate before you build',
  },
  {
    title: 'Product managers',
    body: 'You are going into the next planning meeting with scenario data, not a deck of opinions and a slide of vibes.',
    sig: 'Studio, Pune',
    tag: 'Data over opinion',
  },
  {
    title: 'D2C and physical products',
    body: 'You are about to commit to inventory or a manufacturer. Test pricing, channels, response — before the pallets ship.',
    sig: 'Workshop, Surat',
    tag: 'Test before you manufacture',
  },
  {
    title: 'Side-project builders',
    body: 'You have weekends, not months. Find out if the idea is worth your evenings before you give it a year.',
    sig: 'Desk, Hyderabad',
    tag: 'Know before you commit',
  },
] as const

const TIERS = [
  {
    name: 'Single Issue',
    note: 'For first dossiers',
    price: '₹0',
    sub: 'Free, forever',
    bullets: ['1 active dossier', '500 simulated readers', 'Pre-mortem report', 'Filed in under 2 min'],
    cta: 'Run your first',
    accent: false,
  },
  {
    name: 'Quarterly',
    note: 'For working founders',
    price: '₹1,200',
    sub: 'per month',
    bullets: ['10 active dossiers', '10,000 readers per run', 'Decision Studio', 'Cross-validation 3×', 'Priority press'],
    cta: 'Open a quarterly',
    accent: true,
  },
  {
    name: 'Press Pass',
    note: 'For studios & funds',
    price: 'Talk',
    sub: 'with the editor',
    bullets: ['Unlimited dossiers', 'Custom cohort design', 'Studio collaborators', 'API & exports', 'Named editor'],
    cta: 'Request press pass',
    accent: false,
  },
] as const

/* ─── REVEAL HELPER ─────────────────────────────────── */
function Reveal({
  children,
  delay = 0,
  className = '',
}: {
  children: React.ReactNode
  delay?: number
  className?: string
}) {
  return (
    <motion.div
      initial={{ opacity: 0, y: 28 }}
      whileInView={{ opacity: 1, y: 0 }}
      viewport={{ once: true, margin: '-60px' }}
      transition={{ duration: 0.7, delay, ease: [0.2, 0.7, 0.2, 1] }}
      className={className}
    >
      {children}
    </motion.div>
  )
}

function SectionKicker({ label }: { label: string }) {
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginBottom: 28 }}>
      <div style={{ height: 2, width: 24, background: 'var(--red)' }} />
      <span
        style={{
          fontSize: 10,
          letterSpacing: '0.22em',
          textTransform: 'uppercase',
          color: 'var(--red)',
          fontWeight: 600,
        }}
      >
        {label}
      </span>
    </div>
  )
}

/* ─── ROTATING WORD WITH PAPER FLIP ─────────────────── */
function PaperFlipWord() {
  const [i, setI] = useState(0)
  useEffect(() => {
    const t = setInterval(() => setI(p => (p + 1) % ROTATING.length), 2400)
    return () => clearInterval(t)
  }, [])
  return (
    <span
      style={{
        position: 'relative',
        display: 'inline-block',
        verticalAlign: 'baseline',
        minWidth: '2ch',
        perspective: 800,
      }}
    >
      <AnimatePresence mode="wait">
        <motion.span
          key={ROTATING[i]}
          initial={{ rotateX: 90, opacity: 0, y: 10 }}
          animate={{ rotateX: 0, opacity: 1, y: 0 }}
          exit={{ rotateX: -90, opacity: 0, y: -10 }}
          transition={{ duration: 0.5, ease: [0.76, 0, 0.24, 1] }}
          style={{
            display: 'inline-block',
            color: 'var(--red)',
            fontStyle: 'italic',
            transformOrigin: 'center bottom',
          }}
        >
          {ROTATING[i]}
        </motion.span>
      </AnimatePresence>
    </span>
  )
}

/* ─── LIVE CLOCK STRIP ─────────────────────────────── */
function ClockStrip() {
  const [now, setNow] = useState<Date | null>(null)
  useEffect(() => {
    setNow(new Date())
    const t = setInterval(() => setNow(new Date()), 1000)
    return () => clearInterval(t)
  }, [])
  if (!now) return <span>—</span>
  const fmt = now.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false })
  const date = now.toLocaleDateString('en-GB', { weekday: 'short', day: '2-digit', month: 'short', year: 'numeric' })
  return (
    <span style={{ fontVariantNumeric: 'tabular-nums' }}>
      {date} · {fmt} IST
    </span>
  )
}

/* ─── SCROLL-DRIVEN PRESS PROGRESS BAR ──────────────── */
function PressProgress() {
  const { scrollYProgress } = useScroll()
  const w = useTransform(scrollYProgress, v => `${v * 100}%`)
  return (
    <motion.div
      style={{
        position: 'fixed',
        top: 0,
        left: 0,
        height: 3,
        background: 'var(--red)',
        width: w,
        zIndex: 300,
        transformOrigin: '0 50%',
      }}
      aria-hidden
    />
  )
}

/* ═══════════════════════════════════════════════════════════════ */
export default function LandingPage() {
  const heroRef = useRef<HTMLDivElement>(null)
  const { scrollYProgress } = useScroll({ target: heroRef, offset: ['start start', 'end start'] })
  const heroOpacity = useTransform(scrollYProgress, [0, 0.7], [1, 0])
  const heroY = useTransform(scrollYProgress, [0, 1], [0, 60])

  const [menuOpen, setMenuOpen] = useState(false)
  const [profileOpen, setProfileOpen] = useState(false)
  const [authOpen, setAuthOpen] = useState(false)
  const [authMode, setAuthMode] = useState<'login' | 'signup'>('login')

  const user = useAuthStore(s => s.user)
  const isHydrated = useAuthStore(s => s.isHydrated)
  const logout = useLogout()
  const isAuthed = Boolean(user) || (isHydrated && typeof window !== 'undefined' && authLib.isAuthenticated())

  const openAuth = (m: 'login' | 'signup') => {
    setAuthMode(m)
    setAuthOpen(true)
    setMenuOpen(false)
  }

  const signOut = () => {
    logout()
    setProfileOpen(false)
    setMenuOpen(false)
  }

  return (
    <div style={{ background: 'var(--paper)', minHeight: '100vh', position: 'relative' }}>
      <InkCursor />
      <PressProgress />

      {/* ━━━ MASTHEAD ━━━ */}
      <motion.header
        initial={{ opacity: 0 }}
        animate={{ opacity: 1 }}
        transition={{ duration: 0.6 }}
        style={{
          borderBottom: '3px solid var(--ink)',
          position: 'sticky',
          top: 0,
          zIndex: 50,
          background: 'var(--paper)',
        }}
      >
        {/* Top tier strip */}
        <div
          style={{
            borderBottom: '0.5px solid var(--border-color)',
            padding: '6px 48px',
            display: 'grid',
            gridTemplateColumns: '1fr auto 1fr',
            alignItems: 'center',
            fontSize: 10,
            letterSpacing: '0.14em',
            textTransform: 'uppercase',
            color: 'var(--ink-secondary)',
          }}
        >
          <span style={{ justifySelf: 'start' }}>Vol. I — Issue 04 · The Simulation Broadsheet</span>
          <span style={{ justifySelf: 'center' }}>
            <ClockStrip />
          </span>
          <span style={{ justifySelf: 'end' }}>thecee.app · Early access</span>
        </div>

        {/* Main row */}
        <div
          style={{
            padding: '16px 48px',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
            position: 'relative',
          }}
        >
          <button
            type="button"
            onClick={() => setMenuOpen(true)}
            style={{
              background: 'none',
              border: 'none',
              cursor: 'pointer',
              padding: 4,
              display: 'flex',
              flexDirection: 'column',
              gap: 5,
              width: 28,
            }}
            aria-label="Open menu"
          >
            {[0, 1, 2].map(i => (
              <div
                key={i}
                style={{
                  width: i === 2 ? 16 : 24,
                  height: 1.5,
                  background: 'var(--ink)',
                }}
              />
            ))}
          </button>

          <div style={{ position: 'absolute', left: '50%', transform: 'translateX(-50%)', textAlign: 'center' }}>
            <div
              className="font-serif"
              style={{
                fontSize: 36,
                fontWeight: 900,
                color: 'var(--ink)',
                letterSpacing: '-0.04em',
                lineHeight: 1,
                fontStyle: 'italic',
              }}
            >
              TheCee
            </div>
          </div>

          <div
            style={{ display: 'flex', gap: 20, alignItems: 'center', minWidth: 140, justifyContent: 'flex-end' }}
          >
            {isHydrated && isAuthed ? (
              <Link
                href="/projects"
                style={{
                  fontSize: 11,
                  color: 'var(--paper)',
                  background: 'var(--ink)',
                  padding: '8px 18px',
                  letterSpacing: '0.12em',
                  textTransform: 'uppercase',
                  textDecoration: 'none',
                  fontWeight: 600,
                  display: 'flex',
                  alignItems: 'center',
                  gap: 6,
                }}
              >
                Enter the press <ArrowRight size={11} />
              </Link>
            ) : isHydrated ? (
              <>
                <button
                  type="button"
                  onClick={() => openAuth('login')}
                  style={{
                    background: 'none',
                    border: 'none',
                    cursor: 'pointer',
                    fontSize: 11,
                    color: 'var(--ink-secondary)',
                    letterSpacing: '0.12em',
                    textTransform: 'uppercase',
                    fontFamily: 'inherit',
                    padding: 0,
                  }}
                  onMouseEnter={e => (e.currentTarget.style.color = 'var(--ink)')}
                  onMouseLeave={e => (e.currentTarget.style.color = 'var(--ink-secondary)')}
                >
                  Sign in
                </button>
                <button
                  type="button"
                  onClick={() => openAuth('signup')}
                  style={{
                    fontSize: 11,
                    color: 'var(--paper)',
                    background: 'var(--ink)',
                    border: 'none',
                    padding: '8px 18px',
                    letterSpacing: '0.12em',
                    textTransform: 'uppercase',
                    fontWeight: 600,
                    display: 'flex',
                    alignItems: 'center',
                    gap: 6,
                    cursor: 'pointer',
                    fontFamily: 'inherit',
                  }}
                >
                  Open account <ArrowRight size={11} />
                </button>
              </>
            ) : null}
          </div>
        </div>
      </motion.header>

      {/* ━━━ DRAWER MENU ━━━ */}
      <AnimatePresence>
        {menuOpen && (
          <>
            <motion.div
              key="menu-bg"
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              exit={{ opacity: 0 }}
              transition={{ duration: 0.3 }}
              onClick={() => setMenuOpen(false)}
              style={{
                position: 'fixed',
                inset: 0,
                background: 'rgba(26,23,20,0.4)',
                zIndex: 90,
                backdropFilter: 'blur(2px)',
              }}
            />
            <motion.div
              key="menu-drawer"
              initial={{ x: '-100%' }}
              animate={{ x: 0 }}
              exit={{ x: '-100%' }}
              transition={{ duration: 0.45, ease: [0.25, 0.46, 0.45, 0.94] }}
              style={{
                position: 'fixed',
                top: 0,
                left: 0,
                bottom: 0,
                width: 360,
                background: 'var(--ink)',
                zIndex: 100,
                display: 'flex',
                flexDirection: 'column',
                overflowY: 'auto',
              }}
            >
              <div
                style={{
                  padding: '24px 36px',
                  borderBottom: '0.5px solid rgba(242,236,224,0.08)',
                  display: 'flex',
                  justifyContent: 'space-between',
                  alignItems: 'center',
                }}
              >
                <span
                  className="font-serif"
                  style={{
                    fontSize: 22,
                    fontWeight: 900,
                    fontStyle: 'italic',
                    color: 'var(--paper)',
                    letterSpacing: '-0.03em',
                  }}
                >
                  TheCee
                </span>
                <button
                  type="button"
                  onClick={() => setMenuOpen(false)}
                  style={{
                    background: 'none',
                    border: 'none',
                    cursor: 'pointer',
                    padding: 6,
                    color: 'rgba(242,236,224,0.4)',
                    fontSize: 20,
                    lineHeight: 1,
                  }}
                  aria-label="Close"
                >
                  ✕
                </button>
              </div>

              <nav style={{ padding: '16px 0', flex: 1 }}>
                {[
                  { label: 'How it works', href: '#how' },
                  { label: 'The dossier', href: '#dossier' },
                  { label: 'Letters to the editor', href: '#letters' },
                  { label: 'Subscriptions', href: '#pricing' },
                ].map(({ label, href }, i) => (
                  <motion.a
                    key={label}
                    href={href}
                    initial={{ opacity: 0, x: -20 }}
                    animate={{ opacity: 1, x: 0 }}
                    transition={{ delay: 0.1 + i * 0.07, duration: 0.35 }}
                    onClick={() => setMenuOpen(false)}
                    style={{
                      display: 'flex',
                      justifyContent: 'space-between',
                      alignItems: 'center',
                      padding: '18px 36px',
                      borderBottom: '0.5px solid rgba(242,236,224,0.06)',
                      textDecoration: 'none',
                      color: 'rgba(242,236,224,0.7)',
                      fontSize: 13,
                      letterSpacing: '0.08em',
                      textTransform: 'uppercase',
                    }}
                    onMouseEnter={e => (e.currentTarget.style.color = 'var(--paper)')}
                    onMouseLeave={e => (e.currentTarget.style.color = 'rgba(242,236,224,0.7)')}
                  >
                    {label}
                    <ArrowRight size={12} style={{ opacity: 0.3 }} />
                  </motion.a>
                ))}

                {isAuthed ? (
                  <>
                    <button
                      type="button"
                      onClick={() => setProfileOpen(o => !o)}
                      style={{
                        display: 'flex',
                        justifyContent: 'space-between',
                        alignItems: 'center',
                        width: '100%',
                        padding: '18px 36px',
                        borderBottom: '0.5px solid rgba(242,236,224,0.06)',
                        background: 'none',
                        cursor: 'pointer',
                        color: 'rgba(242,236,224,0.7)',
                        fontSize: 13,
                        letterSpacing: '0.08em',
                        textTransform: 'uppercase',
                        fontFamily: 'inherit',
                        textAlign: 'left',
                        border: 'none',
                      }}
                    >
                      Profile
                      <ChevronDown
                        size={12}
                        style={{
                          opacity: 0.35,
                          transform: profileOpen ? 'rotate(180deg)' : 'rotate(0deg)',
                          transition: 'transform 0.2s ease',
                        }}
                      />
                    </button>
                    <AnimatePresence>
                      {profileOpen && (
                        <motion.div
                          key="profile"
                          initial={{ height: 0, opacity: 0 }}
                          animate={{ height: 'auto', opacity: 1 }}
                          exit={{ height: 0, opacity: 0 }}
                          transition={{ duration: 0.25 }}
                          style={{ overflow: 'hidden', borderBottom: '0.5px solid rgba(242,236,224,0.06)' }}
                        >
                          <div style={{ padding: '16px 36px 20px', background: 'rgba(242,236,224,0.04)' }}>
                            <p
                              style={{
                                fontSize: 9,
                                letterSpacing: '0.18em',
                                textTransform: 'uppercase',
                                color: 'rgba(242,236,224,0.35)',
                                marginBottom: 8,
                              }}
                            >
                              Signed in as
                            </p>
                            <p style={{ fontSize: 13, color: 'var(--paper)', marginBottom: 16, wordBreak: 'break-all' }}>
                              {user?.email ?? '—'}
                            </p>
                            <button
                              type="button"
                              onClick={signOut}
                              style={{
                                fontSize: 11,
                                letterSpacing: '0.1em',
                                textTransform: 'uppercase',
                                color: 'rgba(242,236,224,0.55)',
                                background: 'transparent',
                                border: '0.5px solid rgba(242,236,224,0.2)',
                                padding: '8px 14px',
                                cursor: 'pointer',
                                fontFamily: 'inherit',
                              }}
                            >
                              Sign out
                            </button>
                          </div>
                        </motion.div>
                      )}
                    </AnimatePresence>
                  </>
                ) : (
                  <button
                    type="button"
                    onClick={() => openAuth('login')}
                    style={{
                      display: 'flex',
                      justifyContent: 'space-between',
                      alignItems: 'center',
                      padding: '18px 36px',
                      borderBottom: '0.5px solid rgba(242,236,224,0.06)',
                      background: 'none',
                      border: 'none',
                      width: '100%',
                      color: 'rgba(242,236,224,0.7)',
                      fontSize: 13,
                      letterSpacing: '0.08em',
                      textTransform: 'uppercase',
                      cursor: 'pointer',
                      fontFamily: 'inherit',
                    }}
                  >
                    Sign in
                    <ArrowRight size={12} style={{ opacity: 0.3 }} />
                  </button>
                )}
              </nav>

              {isHydrated && !isAuthed && (
                <div style={{ padding: '28px 36px', borderTop: '0.5px solid rgba(242,236,224,0.08)' }}>
                  <div style={{ width: 20, height: 2, background: 'var(--red)', marginBottom: 14 }} />
                  <p
                    className="font-serif"
                    style={{
                      fontSize: 16,
                      fontStyle: 'italic',
                      fontWeight: 700,
                      color: 'var(--paper)',
                      lineHeight: 1.4,
                      marginBottom: 16,
                      opacity: 0.8,
                    }}
                  >
                    Run your first simulation, free.
                  </p>
                  <button
                    type="button"
                    onClick={() => openAuth('signup')}
                    style={{
                      display: 'flex',
                      alignItems: 'center',
                      justifyContent: 'center',
                      gap: 8,
                      width: '100%',
                      background: 'var(--red)',
                      color: '#fff',
                      border: 'none',
                      padding: '12px 20px',
                      fontSize: 11,
                      letterSpacing: '0.12em',
                      textTransform: 'uppercase',
                      fontWeight: 600,
                      cursor: 'pointer',
                      fontFamily: 'inherit',
                    }}
                  >
                    Open account <ArrowRight size={12} />
                  </button>
                </div>
              )}
            </motion.div>
          </>
        )}
      </AnimatePresence>

      {/* ━━━ HERO — broadsheet front page ━━━ */}
      <section ref={heroRef} style={{ borderBottom: '0.5px solid var(--border-color)', overflow: 'hidden', position: 'relative' }}>
        <motion.div style={{ opacity: heroOpacity, y: heroY }}>
          <div
            style={{
              display: 'grid',
              gridTemplateColumns: '0.85fr 2.4fr 1fr',
              minHeight: '82vh',
            }}
          >
            {/* LEFT spine */}
            <div
              style={{
                borderRight: '0.5px solid var(--border-color)',
                padding: '40px 30px',
                display: 'flex',
                flexDirection: 'column',
                justifyContent: 'space-between',
              }}
            >
              <div>
                <div
                  style={{
                    fontSize: 9,
                    letterSpacing: '0.22em',
                    textTransform: 'uppercase',
                    color: 'var(--ink-secondary)',
                    marginBottom: 18,
                  }}
                >
                  In this issue
                </div>
                {[
                  'Idea validation',
                  'Risk discovery',
                  'Revenue forecasting',
                  'Launch readiness',
                  'Pricing confidence',
                  'Pre-mortem report',
                ].map((item, i) => (
                  <a
                    key={item}
                    href="#how"
                    style={{
                      display: 'flex',
                      alignItems: 'center',
                      gap: 10,
                      padding: '10px 0',
                      borderBottom: '0.5px solid var(--border-color)',
                      fontSize: 11,
                      color: 'var(--ink-secondary)',
                      textDecoration: 'none',
                      transition: 'color 0.2s, padding-left 0.2s',
                    }}
                    onMouseEnter={e => {
                      e.currentTarget.style.color = 'var(--red)'
                      e.currentTarget.style.paddingLeft = '6px'
                    }}
                    onMouseLeave={e => {
                      e.currentTarget.style.color = 'var(--ink-secondary)'
                      e.currentTarget.style.paddingLeft = '0px'
                    }}
                  >
                    <span
                      style={{
                        fontVariantNumeric: 'tabular-nums',
                        color: 'var(--ink-tertiary)',
                        fontSize: 9,
                        letterSpacing: '0.18em',
                        minWidth: 22,
                      }}
                    >
                      {String(i + 1).padStart(2, '0')}
                    </span>
                    <Minus size={8} color="var(--red)" />
                    <span style={{ flex: 1 }}>{item}</span>
                  </a>
                ))}
              </div>

              <div>
                <div style={{ width: 24, height: 2, background: 'var(--red)', marginBottom: 12 }} />
                <p className="font-serif" style={{ fontSize: 14, fontStyle: 'italic', fontWeight: 700, color: 'var(--ink)', lineHeight: 1.5 }}>
                  TheCee simulates reality before you commit to it.
                </p>
              </div>
            </div>

            {/* CENTRE story */}
            <div
              style={{
                borderRight: '0.5px solid var(--border-color)',
                padding: '48px 56px',
                display: 'flex',
                flexDirection: 'column',
                justifyContent: 'space-between',
              }}
            >
              <div>
                <SectionKicker label="Cover Story · Vol. I — 04" />

                <TypesetHeadline
                  words={['Will', 'your']}
                  style={{ fontSize: 'clamp(56px, 7.4vw, 104px)' }}
                />
                <div
                  className="font-serif"
                  style={{
                    fontSize: 'clamp(56px, 7.4vw, 104px)',
                    fontWeight: 900,
                    letterSpacing: '-0.035em',
                    lineHeight: 0.95,
                    color: 'var(--ink)',
                  }}
                >
                  <PaperFlipWord />
                  <br />
                  <motion.span
                    initial={{ opacity: 0, y: 14 }}
                    animate={{ opacity: 1, y: 0 }}
                    transition={{ duration: 0.7, delay: 0.6 }}
                    style={{ color: 'var(--ink-tertiary)', fontStyle: 'italic' }}
                  >
                    actually work?
                  </motion.span>
                </div>

                <div style={{ height: 0.5, background: 'var(--border-color)', margin: '28px 0' }} />

                <motion.p
                  className="lead-para"
                  initial={{ opacity: 0 }}
                  animate={{ opacity: 1 }}
                  transition={{ duration: 0.7, delay: 0.85 }}
                  style={{
                    fontSize: 17,
                    color: 'var(--ink-secondary)',
                    lineHeight: 1.85,
                    maxWidth: 540,
                    fontWeight: 300,
                    marginBottom: 36,
                  }}
                >
                  TheCee stress-tests your idea against thousands of real-world
                  scenarios before you commit — clarity that no amount of
                  planning, advice, or gut feeling can ever match. Filed in
                  under two minutes.
                </motion.p>

                <motion.div
                  initial={{ opacity: 0, y: 12 }}
                  animate={{ opacity: 1, y: 0 }}
                  transition={{ duration: 0.6, delay: 1 }}
                  style={{ display: 'flex', alignItems: 'center', gap: 24, flexWrap: 'wrap' }}
                >
                  <MagneticCTA
                    onClick={() => openAuth('signup')}
                    style={{
                      background: 'var(--ink)',
                      color: 'var(--paper)',
                      padding: '14px 28px',
                      fontSize: 11,
                      letterSpacing: '0.16em',
                      textTransform: 'uppercase',
                      fontWeight: 600,
                    }}
                  >
                    Validate your idea <ArrowRight size={12} />
                  </MagneticCTA>

                  <a
                    href="#how"
                    style={{
                      fontSize: 11,
                      color: 'var(--ink-secondary)',
                      letterSpacing: '0.12em',
                      textTransform: 'uppercase',
                      textDecoration: 'none',
                      borderBottom: '0.5px solid var(--border-color)',
                      paddingBottom: 2,
                    }}
                    onMouseEnter={e => (e.currentTarget.style.color = 'var(--ink)')}
                    onMouseLeave={e => (e.currentTarget.style.color = 'var(--ink-secondary)')}
                  >
                    Read how it works →
                  </a>
                </motion.div>
              </div>

              {/* Pull quote */}
              <div
                style={{
                  borderTop: '0.5px solid var(--border-color)',
                  paddingTop: 28,
                  marginTop: 40,
                  display: 'grid',
                  gridTemplateColumns: '1.4fr 1fr',
                  gap: 32,
                  alignItems: 'center',
                }}
              >
                <p
                  className="font-serif"
                  style={{
                    fontSize: 16,
                    fontStyle: 'italic',
                    fontWeight: 700,
                    color: 'var(--ink)',
                    lineHeight: 1.5,
                  }}
                >
                  &ldquo;Know before you build. Not after you have spent six
                  months on something that will not work.&rdquo;
                </p>
                <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 28 }}>
                  {[{ v: '243+', l: 'Founders' }, { v: '1.4M+', l: 'Scenarios' }].map(({ v, l }) => (
                    <div key={l} style={{ textAlign: 'right' }}>
                      <div
                        className="font-serif numeral"
                        style={{ fontSize: 28, color: 'var(--ink)', letterSpacing: '-0.02em', lineHeight: 1 }}
                      >
                        {v}
                      </div>
                      <div style={{ fontSize: 9, color: 'var(--ink-tertiary)', letterSpacing: '0.16em', textTransform: 'uppercase', marginTop: 4 }}>
                        {l}
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            </div>

            {/* RIGHT — live counters + CTA */}
            <div
              style={{
                padding: '40px 30px',
                display: 'flex',
                flexDirection: 'column',
                justifyContent: 'space-between',
                gap: 20,
              }}
            >
              <div>
                <div
                  style={{
                    fontSize: 9,
                    letterSpacing: '0.22em',
                    textTransform: 'uppercase',
                    color: 'var(--ink-secondary)',
                    marginBottom: 14,
                  }}
                >
                  At the press
                </div>
                <LiveCounters />
              </div>

              <div
                style={{
                  border: '1.5px solid var(--ink)',
                  padding: 22,
                  background: 'var(--paper-dark)',
                }}
              >
                <div
                  style={{
                    fontSize: 9,
                    letterSpacing: '0.22em',
                    textTransform: 'uppercase',
                    color: 'var(--red)',
                    marginBottom: 12,
                    fontWeight: 600,
                  }}
                >
                  Free to start
                </div>
                <p
                  className="font-serif"
                  style={{ fontSize: 16, fontWeight: 800, color: 'var(--ink)', lineHeight: 1.3, marginBottom: 16, fontStyle: 'italic' }}
                >
                  Run your first simulation at no cost.
                </p>
                <button
                  type="button"
                  onClick={() => openAuth('signup')}
                  style={{
                    display: 'block',
                    width: '100%',
                    textAlign: 'center',
                    background: 'var(--red)',
                    color: '#fff',
                    border: 'none',
                    padding: 10,
                    fontSize: 10,
                    letterSpacing: '0.16em',
                    textTransform: 'uppercase',
                    fontWeight: 600,
                    cursor: 'pointer',
                    fontFamily: 'inherit',
                    transition: 'opacity 0.2s',
                  }}
                  onMouseEnter={e => (e.currentTarget.style.opacity = '0.85')}
                  onMouseLeave={e => (e.currentTarget.style.opacity = '1')}
                >
                  Begin issue 01 →
                </button>
              </div>
            </div>
          </div>
        </motion.div>
      </section>

      {/* ━━━ PRESS TICKER ━━━ */}
      <PressTicker />

      {/* ━━━ HOW IT WORKS — letterpress plates ━━━ */}
      <section id="how" style={{ borderBottom: '0.5px solid var(--border-color)' }}>
        <div style={{ maxWidth: 1280, margin: '0 auto', padding: '96px 48px 80px' }}>
          <Reveal>
            <SectionKicker label="The Process" />
            <h2
              className="font-serif"
              style={{
                fontSize: 'clamp(40px, 4.4vw, 68px)',
                fontWeight: 900,
                fontStyle: 'italic',
                color: 'var(--ink)',
                lineHeight: 1.02,
                letterSpacing: '-0.035em',
                marginBottom: 64,
                maxWidth: 820,
              }}
            >
              Three plates, three impressions, <span style={{ color: 'var(--red)' }}>one</span> certainty.
            </h2>
          </Reveal>

          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)' }}>
            {PLATES.map((p, i) => (
              <Reveal key={p.n} delay={i * 0.1}>
                <Plate
                  index={i}
                  total={PLATES.length}
                  numeral={p.n}
                  kicker={p.kicker}
                  title={p.title}
                  body={p.body}
                />
              </Reveal>
            ))}
          </div>
        </div>
      </section>

      {/* ━━━ EXISTING SIMULATION TIMELINE (live animation) ━━━ */}
      <SimulationTimeline />

      {/* ━━━ DOSSIER SPECIMEN ━━━ */}
      <section id="dossier" style={{ borderBottom: '0.5px solid var(--border-color)', background: 'var(--paper)' }}>
        <div style={{ maxWidth: 1280, margin: '0 auto', padding: '96px 48px' }}>
          <div style={{ display: 'grid', gridTemplateColumns: '220px 1fr', gap: 72, alignItems: 'flex-start' }}>
            <div style={{ position: 'sticky', top: 130 }}>
              <span className="font-serif numeral" style={{ fontSize: 38, color: 'var(--ink-tertiary)' }}>
                IV
              </span>
              <div style={{ marginTop: 18, fontSize: 10, letterSpacing: '0.22em', textTransform: 'uppercase', color: 'var(--ink-secondary)' }}>
                The Index
              </div>
              <div style={{ width: 24, height: 2, background: 'var(--red)', margin: '14px 0' }} />
              <p className="font-serif" style={{ fontSize: 14, fontStyle: 'italic', fontWeight: 600, color: 'var(--ink-secondary)', lineHeight: 1.55, maxWidth: 200 }}>
                Every dossier you file is stamped, dated, and put on the
                ledger — exactly like the four below.
              </p>
            </div>

            <div>
              <Reveal>
                <SectionKicker label="A Specimen Index" />
                <h2
                  className="font-serif"
                  style={{
                    fontSize: 'clamp(34px, 3.8vw, 56px)',
                    fontWeight: 900,
                    fontStyle: 'italic',
                    color: 'var(--ink)',
                    lineHeight: 1.02,
                    letterSpacing: '-0.03em',
                    marginBottom: 44,
                  }}
                >
                  Your <span style={{ color: 'var(--red)' }}>ideas</span>, under review.
                </h2>
              </Reveal>
              <DossierSpecimen />
              <div style={{ marginTop: 36 }}>
                <button
                  type="button"
                  onClick={() => openAuth('signup')}
                  className="btn-ghost"
                  style={{ fontFamily: 'inherit' }}
                >
                  Open your own index <ArrowUpRight size={13} />
                </button>
              </div>
            </div>
          </div>
        </div>
      </section>

      {/* ━━━ FEATURE SHOWCASE (existing live animation) ━━━ */}
      <FeatureShowcase />

      {/* ━━━ LETTERS TO THE EDITOR ━━━ */}
      <section id="letters" style={{ borderBottom: '0.5px solid var(--border-color)', background: 'var(--paper-dark)' }}>
        <div style={{ maxWidth: 1280, margin: '0 auto', padding: '96px 48px' }}>
          <Reveal>
            <SectionKicker label="Letters to the Editor" />
            <h2
              className="font-serif"
              style={{
                fontSize: 'clamp(36px, 3.8vw, 56px)',
                fontWeight: 900,
                fontStyle: 'italic',
                color: 'var(--ink)',
                lineHeight: 1.02,
                letterSpacing: '-0.03em',
                marginBottom: 64,
                maxWidth: 720,
              }}
            >
              Built for people who <span style={{ color: 'var(--red)' }}>cannot</span> afford to guess.
            </h2>
          </Reveal>

          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(2, 1fr)' }}>
            {LETTERS.map((l, i) => (
              <Reveal key={l.title} delay={i * 0.08}>
                <article
                  style={{
                    padding: 40,
                    borderTop: '0.5px solid var(--border-color)',
                    borderRight: i % 2 === 0 ? '0.5px solid var(--border-color)' : 'none',
                    background: 'var(--paper-dark)',
                    transition: 'background 0.3s',
                    position: 'relative',
                  }}
                  onMouseEnter={e => (e.currentTarget.style.background = 'var(--paper)')}
                  onMouseLeave={e => (e.currentTarget.style.background = 'var(--paper-dark)')}
                >
                  <div
                    style={{
                      display: 'inline-block',
                      fontSize: 9,
                      color: 'var(--red)',
                      letterSpacing: '0.18em',
                      textTransform: 'uppercase',
                      fontWeight: 600,
                      borderLeft: '2px solid var(--red)',
                      paddingLeft: 8,
                      marginBottom: 22,
                    }}
                  >
                    {l.tag}
                  </div>
                  <h3
                    className="font-serif"
                    style={{
                      fontSize: 24,
                      fontWeight: 800,
                      fontStyle: 'italic',
                      color: 'var(--ink)',
                      lineHeight: 1.2,
                      marginBottom: 14,
                    }}
                  >
                    {l.title}
                  </h3>
                  <p
                    className="font-serif"
                    style={{
                      fontSize: 16,
                      color: 'var(--ink)',
                      lineHeight: 1.7,
                      fontWeight: 300,
                      letterSpacing: '-0.005em',
                    }}
                  >
                    {l.body}
                  </p>
                  <div
                    style={{
                      marginTop: 22,
                      paddingTop: 14,
                      borderTop: '0.5px solid var(--border-color)',
                      fontSize: 10,
                      letterSpacing: '0.18em',
                      textTransform: 'uppercase',
                      color: 'var(--ink-tertiary)',
                    }}
                  >
                    — {l.sig}
                  </div>
                </article>
              </Reveal>
            ))}
          </div>
        </div>
      </section>

      {/* ━━━ SUBSCRIPTIONS ━━━ */}
      <section id="pricing" style={{ borderBottom: '0.5px solid var(--border-color)' }}>
        <div style={{ maxWidth: 1280, margin: '0 auto', padding: '96px 48px' }}>
          <Reveal>
            <SectionKicker label="Subscriptions · The Press Tiers" />
            <h2
              className="font-serif"
              style={{
                fontSize: 'clamp(36px, 3.8vw, 56px)',
                fontWeight: 900,
                fontStyle: 'italic',
                color: 'var(--ink)',
                lineHeight: 1.02,
                letterSpacing: '-0.03em',
                marginBottom: 64,
                maxWidth: 720,
              }}
            >
              Subscribe to the <span style={{ color: 'var(--red)' }}>broadsheet</span>.
            </h2>
          </Reveal>

          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', border: '0.5px solid var(--ink)' }}>
            {TIERS.map((t, i) => (
              <Reveal key={t.name} delay={i * 0.1}>
                <div
                  style={{
                    padding: 36,
                    borderRight: i < TIERS.length - 1 ? '0.5px solid var(--border-color)' : 'none',
                    background: t.accent ? 'var(--ink)' : 'var(--paper)',
                    color: t.accent ? 'var(--paper)' : 'var(--ink)',
                    minHeight: 460,
                    display: 'flex',
                    flexDirection: 'column',
                  }}
                >
                  <div
                    style={{
                      fontSize: 10,
                      letterSpacing: '0.22em',
                      textTransform: 'uppercase',
                      color: t.accent ? 'var(--red)' : 'var(--red)',
                      fontWeight: 600,
                      marginBottom: 12,
                    }}
                  >
                    {t.note}
                  </div>
                  <h3
                    className="font-serif"
                    style={{
                      fontSize: 30,
                      fontWeight: 900,
                      fontStyle: 'italic',
                      letterSpacing: '-0.03em',
                      marginBottom: 18,
                      color: t.accent ? 'var(--paper)' : 'var(--ink)',
                    }}
                  >
                    {t.name}
                  </h3>
                  <div
                    className="font-serif numeral"
                    style={{
                      fontSize: 56,
                      letterSpacing: '-0.04em',
                      lineHeight: 1,
                      color: t.accent ? 'var(--paper)' : 'var(--ink)',
                    }}
                  >
                    {t.price}
                  </div>
                  <div
                    style={{
                      fontSize: 10,
                      letterSpacing: '0.18em',
                      textTransform: 'uppercase',
                      color: t.accent ? 'rgba(242,236,224,0.5)' : 'var(--ink-tertiary)',
                      marginTop: 6,
                      marginBottom: 30,
                    }}
                  >
                    {t.sub}
                  </div>

                  <ul style={{ listStyle: 'none', padding: 0, margin: 0, flex: 1 }}>
                    {t.bullets.map(b => (
                      <li
                        key={b}
                        style={{
                          padding: '10px 0',
                          borderBottom: t.accent
                            ? '0.5px solid rgba(242,236,224,0.1)'
                            : '0.5px solid var(--border-color)',
                          fontSize: 13,
                          display: 'flex',
                          alignItems: 'center',
                          gap: 12,
                          color: t.accent ? 'rgba(242,236,224,0.85)' : 'var(--ink-secondary)',
                        }}
                      >
                        <span style={{ width: 6, height: 6, background: 'var(--red)', display: 'inline-block', flexShrink: 0 }} />
                        {b}
                      </li>
                    ))}
                  </ul>

                  <button
                    type="button"
                    onClick={() => openAuth('signup')}
                    style={{
                      marginTop: 28,
                      background: t.accent ? 'var(--red)' : 'var(--ink)',
                      color: 'var(--paper)',
                      border: 'none',
                      padding: '14px 22px',
                      fontSize: 11,
                      letterSpacing: '0.16em',
                      textTransform: 'uppercase',
                      fontWeight: 700,
                      cursor: 'pointer',
                      fontFamily: 'inherit',
                      display: 'inline-flex',
                      alignItems: 'center',
                      justifyContent: 'center',
                      gap: 10,
                      transition: 'background 0.2s',
                    }}
                    onMouseEnter={e => {
                      ;(e.currentTarget as HTMLButtonElement).style.background = t.accent ? '#a93226' : 'var(--red)'
                    }}
                    onMouseLeave={e => {
                      ;(e.currentTarget as HTMLButtonElement).style.background = t.accent ? 'var(--red)' : 'var(--ink)'
                    }}
                  >
                    {t.cta} <ArrowRight size={12} />
                  </button>
                </div>
              </Reveal>
            ))}
          </div>
        </div>
      </section>

      {/* ━━━ FINAL CTA — The Press Room ━━━ */}
      <section style={{ background: 'var(--ink)', borderBottom: '3px solid var(--ink)' }}>
        <div
          style={{
            maxWidth: 1280,
            margin: '0 auto',
            padding: '120px 48px',
            display: 'grid',
            gridTemplateColumns: '1.5fr 1fr',
            gap: 80,
            alignItems: 'center',
          }}
        >
          <Reveal>
            <div style={{ height: 2, width: 24, background: 'var(--red)', marginBottom: 24 }} />
            <h2
              className="font-serif"
              style={{
                fontSize: 'clamp(40px, 4.6vw, 72px)',
                fontWeight: 900,
                fontStyle: 'italic',
                color: 'var(--paper)',
                lineHeight: 1.02,
                letterSpacing: '-0.035em',
                marginBottom: 28,
              }}
            >
              Your next decision
              <br />
              <span style={{ color: 'rgba(242,236,224,0.3)' }}>deserves certainty.</span>
            </h2>
            <p
              style={{
                fontSize: 15,
                color: 'rgba(242,236,224,0.55)',
                lineHeight: 1.85,
                marginBottom: 38,
                maxWidth: 460,
                fontWeight: 300,
              }}
            >
              Stop planning. Stop guessing. Start simulating — and know before
              you build. The press is open. Walk into the room.
            </p>
            <MagneticCTA
              onClick={() => openAuth('signup')}
              style={{
                background: 'var(--red)',
                color: '#fff',
                padding: '16px 34px',
                fontSize: 11,
                letterSpacing: '0.16em',
                textTransform: 'uppercase',
                fontWeight: 700,
              }}
            >
              Validate your idea, free <ArrowRight size={14} />
            </MagneticCTA>
          </Reveal>

          <Reveal delay={0.15}>
            <div style={{ borderLeft: '0.5px solid rgba(242,236,224,0.1)', paddingLeft: 60 }}>
              <div style={{ height: 2, width: 20, background: 'var(--red)', marginBottom: 16 }} />
              <p
                className="font-serif"
                style={{
                  fontSize: 22,
                  fontStyle: 'italic',
                  fontWeight: 700,
                  color: 'var(--paper)',
                  lineHeight: 1.5,
                  marginBottom: 22,
                  opacity: 0.9,
                }}
              >
                &ldquo;Every decision made without simulation is a decision
                made blind.&rdquo;
              </p>
              <p style={{ fontSize: 10, color: 'rgba(242,236,224,0.4)', letterSpacing: '0.18em', textTransform: 'uppercase' }}>
                — TheCee, 2026
              </p>
            </div>
          </Reveal>
        </div>
      </section>

      {/* ━━━ COLOPHON FOOTER ━━━ */}
      <footer style={{ background: 'var(--ink)', borderTop: '0.5px solid rgba(242,236,224,0.08)' }}>
        <div
          style={{
            maxWidth: 1280,
            margin: '0 auto',
            padding: '56px 48px 28px',
            display: 'grid',
            gridTemplateColumns: '1.6fr 1fr 1fr 1fr',
            gap: 40,
          }}
        >
          <div>
            <div
              className="font-serif"
              style={{ fontSize: 26, fontWeight: 900, fontStyle: 'italic', color: 'var(--paper)', letterSpacing: '-0.03em' }}
            >
              TheCee
            </div>
            <p
              style={{
                marginTop: 14,
                fontSize: 12,
                color: 'rgba(242,236,224,0.4)',
                lineHeight: 1.7,
                maxWidth: 280,
              }}
            >
              The simulation broadsheet. Filed quarterly, on the Internet, since 2026.
            </p>
          </div>

          {[
            { h: 'Pages', items: ['Cover', 'How it works', 'Dossier', 'Letters', 'Subscriptions'] },
            { h: 'Press room', items: ['About', 'Editor', 'Methodology', 'Press kit'] },
            { h: 'Colophon', items: ['Privacy', 'Terms', 'Status', 'Contact'] },
          ].map(col => (
            <div key={col.h}>
              <div style={{ fontSize: 9, letterSpacing: '0.22em', textTransform: 'uppercase', color: 'rgba(242,236,224,0.45)', marginBottom: 16 }}>
                {col.h}
              </div>
              {col.items.map(it => (
                <a
                  key={it}
                  href="#"
                  style={{
                    display: 'block',
                    padding: '6px 0',
                    fontSize: 12,
                    color: 'rgba(242,236,224,0.65)',
                    textDecoration: 'none',
                    transition: 'color 0.2s',
                  }}
                  onMouseEnter={e => (e.currentTarget.style.color = 'var(--red)')}
                  onMouseLeave={e => (e.currentTarget.style.color = 'rgba(242,236,224,0.65)')}
                >
                  {it}
                </a>
              ))}
            </div>
          ))}
        </div>

        <div
          style={{
            borderTop: '0.5px solid rgba(242,236,224,0.08)',
            padding: '18px 48px',
            display: 'flex',
            justifyContent: 'space-between',
            alignItems: 'center',
            fontSize: 10,
            letterSpacing: '0.16em',
            textTransform: 'uppercase',
            color: 'rgba(242,236,224,0.35)',
          }}
        >
          <span>© 2026 TheCee — Simulate before you build</span>
          <span>Set in Playfair & DM Sans · Printed in IST</span>
        </div>
      </footer>

      {/* ━━━ INLINE AUTH ━━━ */}
      <InlineAuth open={authOpen} onClose={() => setAuthOpen(false)} initialMode={authMode} />
    </div>
  )
}

/* ─── PROCESS PLATE — ink-stamp on hover ────────────── */
function Plate({
  index,
  total,
  numeral,
  kicker,
  title,
  body,
}: {
  index: number
  total: number
  numeral: string
  kicker: string
  title: string
  body: string
}) {
  return (
    <div
      style={{
        position: 'relative',
        padding: '40px 36px 44px',
        paddingLeft: index === 0 ? 0 : 36,
        paddingRight: index === total - 1 ? 0 : 36,
        borderRight: index < total - 1 ? '0.5px solid var(--border-color)' : 'none',
        minHeight: 360,
        display: 'flex',
        flexDirection: 'column',
        justifyContent: 'space-between',
        overflow: 'hidden',
        cursor: 'default',
      }}
      onMouseEnter={e => {
        const stamp = e.currentTarget.querySelector<HTMLElement>('[data-ink-stamp]')
        if (stamp) {
          stamp.style.transform = 'translateY(0%)'
          stamp.style.opacity = '1'
        }
      }}
      onMouseLeave={e => {
        const stamp = e.currentTarget.querySelector<HTMLElement>('[data-ink-stamp]')
        if (stamp) {
          stamp.style.transform = 'translateY(102%)'
          stamp.style.opacity = '0.0'
        }
      }}
    >
      {/* Sliding ink stamp behind content */}
      <div
        data-ink-stamp
        aria-hidden
        style={{
          position: 'absolute',
          inset: 0,
          background: 'rgba(192,57,43,0.04)',
          borderTop: '2px solid var(--red)',
          transform: 'translateY(102%)',
          opacity: 0,
          transition: 'transform 380ms cubic-bezier(.2,.7,.2,1), opacity 280ms ease',
          pointerEvents: 'none',
          zIndex: 0,
        }}
      />

      <div style={{ position: 'relative', zIndex: 1 }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: 24 }}>
          <span
            style={{
              fontSize: 9,
              color: 'var(--red)',
              letterSpacing: '0.22em',
              textTransform: 'uppercase',
              fontWeight: 600,
            }}
          >
            {kicker}
          </span>
          <span
            className="font-serif numeral"
            style={{
              fontSize: 64,
              color: 'var(--paper-dark)',
              lineHeight: 1,
              letterSpacing: '-0.04em',
            }}
          >
            {numeral}
          </span>
        </div>
        <div style={{ height: 2, background: 'var(--ink)', width: 24, marginBottom: 22 }} />
        <h3
          className="font-serif"
          style={{
            fontSize: 26,
            fontWeight: 800,
            fontStyle: 'italic',
            color: 'var(--ink)',
            lineHeight: 1.2,
            letterSpacing: '-0.015em',
            marginBottom: 14,
          }}
        >
          {title}
        </h3>
        <p style={{ fontSize: 14, color: 'var(--ink-secondary)', lineHeight: 1.85, fontWeight: 300 }}>
          {body}
        </p>
      </div>
    </div>
  )
}
