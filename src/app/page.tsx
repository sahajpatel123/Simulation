'use client'

import { useEffect, useRef, useState, type CSSProperties } from 'react'
import { AnimatePresence, motion, useScroll, useSpring } from 'framer-motion'
import Link from 'next/link'
import { ArrowRight, ArrowUpRight, ChevronDown } from 'lucide-react'

import MagneticCTA from '@/components/landing/MagneticCTA'
import PressTicker from '@/components/landing/PressTicker'
import DossierSpecimen from '@/components/landing/DossierSpecimen'
import InlineAuth from '@/components/landing/InlineAuth'
import HeroCover from '@/components/landing/HeroCover'
import ProcessReel from '@/components/landing/ProcessReel'
import CountUp from '@/components/landing/CountUp'

import { useAuthStore } from '@/store/auth.store'
import { auth as authLib } from '@/lib/auth'
import { useLogout } from '@/hooks/useAuth'

/* ─── COPY ──────────────────────────────────────────── */
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
    body:
      'You are launching your first product with limited runway. Run it through the press before you spend it.',
    sig: 'Field, Bangalore',
    tag: 'Validate before you build',
  },
  {
    title: 'Product managers',
    body:
      'You are going into the next planning meeting with scenario data, not a deck of opinions and a slide of vibes.',
    sig: 'Studio, Pune',
    tag: 'Data over opinion',
  },
  {
    title: 'D2C and physical products',
    body:
      'You are about to commit to inventory or a manufacturer. Test pricing, channels, response — before the pallets ship.',
    sig: 'Workshop, Surat',
    tag: 'Test before you manufacture',
  },
  {
    title: 'Side-project builders',
    body:
      'You have weekends, not months. Find out if the idea is worth your evenings before you give it a year.',
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
    bullets: [
      '10 active dossiers',
      '10,000 readers per run',
      'Decision Studio',
      'Cross-validation 3×',
      'Priority press',
    ],
    cta: 'Open a quarterly',
    accent: true,
  },
  {
    name: 'Press Pass',
    note: 'For studios & funds',
    price: 'Talk',
    sub: 'with the editor',
    bullets: [
      'Unlimited dossiers',
      'Custom cohort design',
      'Studio collaborators',
      'API & exports',
      'Named editor',
    ],
    cta: 'Request press pass',
    accent: false,
  },
] as const

/* ─── REVEAL HELPER ─────────────────────────────────── */
function Reveal({
  children,
  delay = 0,
  className = '',
  y = 28,
}: {
  children: React.ReactNode
  delay?: number
  className?: string
  y?: number
}) {
  return (
    <motion.div
      initial={{ opacity: 0, y }}
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
          letterSpacing: '0.3em',
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

/* ─── SCROLL-DRIVEN PRESS PROGRESS BAR ──────────────── */
function PressProgress() {
  const { scrollYProgress } = useScroll()
  const scaleX = useSpring(scrollYProgress, { stiffness: 180, damping: 34, mass: 0.3 })
  return (
    <motion.div
      style={{
        position: 'fixed',
        top: 0,
        left: 0,
        right: 0,
        height: 3,
        background: 'var(--red)',
        transformOrigin: '0 50%',
        scaleX,
        zIndex: 300,
      }}
      aria-hidden
    />
  )
}

/** Live folio line — lives in the sticky masthead so the hero cover can start at the rules. */
function BroadsheetFolio() {
  const [now, setNow] = useState<Date | null>(null)
  useEffect(() => {
    setNow(new Date())
    const id = setInterval(() => setNow(new Date()), 1000)
    return () => clearInterval(id)
  }, [])
  const dateLabel = now
    ? now.toLocaleDateString('en-GB', {
        weekday: 'long',
        day: '2-digit',
        month: 'long',
        year: 'numeric',
      })
    : '—'
  const timeLabel = now
    ? now.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', hour12: false })
    : '—'

  const inset = 'clamp(16px, 4vw, 40px)'

  return (
    <motion.div
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      transition={{ duration: 0.45, delay: 0.08 }}
      style={{
        position: 'relative',
        borderTop: '0.5px solid var(--border-color)',
        minHeight: 30,
        fontSize: 9,
        letterSpacing: '0.22em',
        textTransform: 'uppercase',
        color: 'var(--ink-secondary)',
        fontWeight: 500,
      }}
    >
      <span
        style={{
          position: 'absolute',
          left: inset,
          top: '50%',
          transform: 'translateY(-50%)',
          maxWidth: 'min(42%, calc(100% - 120px))',
          overflow: 'hidden',
          textOverflow: 'ellipsis',
          whiteSpace: 'nowrap',
        }}
      >
        Vol. I — Issue 04
      </span>
      <span
        style={{
          position: 'absolute',
          right: inset,
          top: '50%',
          transform: 'translateY(-50%)',
          maxWidth: 'min(48%, calc(100% - 120px))',
          overflow: 'hidden',
          textOverflow: 'ellipsis',
          whiteSpace: 'nowrap',
          textAlign: 'right',
          fontVariantNumeric: 'tabular-nums',
          color: 'var(--ink-tertiary)',
        }}
      >
        {dateLabel} · {timeLabel}
      </span>
    </motion.div>
  )
}

/* ═══════════════════════════════════════════════════════════════ */
export default function LandingPage() {
  const [menuOpen, setMenuOpen] = useState(false)
  const [profileOpen, setProfileOpen] = useState(false)
  const [authOpen, setAuthOpen] = useState(false)
  const [authMode, setAuthMode] = useState<'login' | 'signup'>('login')

  const user = useAuthStore((s) => s.user)
  const isHydrated = useAuthStore((s) => s.isHydrated)
  const logout = useLogout()
  const isAuthed =
    Boolean(user) || (isHydrated && typeof window !== 'undefined' && authLib.isAuthenticated())

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

  const scrollToHow = () => {
    const el = document.getElementById('how')
    if (el) el.scrollIntoView({ behavior: 'smooth', block: 'start' })
  }

  return (
    <div style={{ background: 'var(--paper)', minHeight: '100vh', position: 'relative' }}>
      <PressProgress />

      {/* ━━━ MASTHEAD — compact sticky bar ━━━ */}
      <motion.header
        initial={{ opacity: 0, y: -12 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.5 }}
        style={{
          borderBottom: '0.5px solid var(--border-color)',
          position: 'sticky',
          top: 0,
          zIndex: 50,
          background: 'rgba(242,236,224,0.92)',
          backdropFilter: 'blur(10px)',
          WebkitBackdropFilter: 'blur(10px)',
        }}
      >
        <div
          style={{
            padding: '14px 40px',
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
            {[0, 1, 2].map((i) => (
              <div
                key={i}
                style={{
                  width: i === 2 ? 16 : 24,
                  height: 1.5,
                  background: 'var(--ink)',
                  transition: 'width 220ms ease',
                }}
              />
            ))}
          </button>

          <div
            style={{
              position: 'absolute',
              left: '50%',
              transform: 'translateX(-50%)',
              textAlign: 'center',
            }}
          >
            <div
              className="font-serif"
              style={{
                fontSize: 26,
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
            style={{
              display: 'flex',
              gap: 16,
              alignItems: 'center',
              minWidth: 140,
              justifyContent: 'flex-end',
            }}
          >
            {isHydrated && isAuthed ? (
              <Link
                href="/projects"
                style={{
                  fontSize: 11,
                  color: 'var(--paper)',
                  background: 'var(--ink)',
                  padding: '8px 18px',
                  letterSpacing: '0.16em',
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
                    letterSpacing: '0.16em',
                    textTransform: 'uppercase',
                    fontFamily: 'inherit',
                    padding: 0,
                  }}
                  onMouseEnter={(e) => (e.currentTarget.style.color = 'var(--ink)')}
                  onMouseLeave={(e) => (e.currentTarget.style.color = 'var(--ink-secondary)')}
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
                    letterSpacing: '0.16em',
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
        <BroadsheetFolio />
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
                    onMouseEnter={(e) => (e.currentTarget.style.color = 'var(--paper)')}
                    onMouseLeave={(e) =>
                      (e.currentTarget.style.color = 'rgba(242,236,224,0.7)')
                    }
                  >
                    {label}
                    <ArrowRight size={12} style={{ opacity: 0.3 }} />
                  </motion.a>
                ))}

                {isAuthed ? (
                  <>
                    <button
                      type="button"
                      onClick={() => setProfileOpen((o) => !o)}
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
                          style={{
                            overflow: 'hidden',
                            borderBottom: '0.5px solid rgba(242,236,224,0.06)',
                          }}
                        >
                          <div
                            style={{ padding: '16px 36px 20px', background: 'rgba(242,236,224,0.04)' }}
                          >
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
                            <p
                              style={{
                                fontSize: 13,
                                color: 'var(--paper)',
                                marginBottom: 16,
                                wordBreak: 'break-all',
                              }}
                            >
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

      {/* ━━━ HERO — a quiet cover ━━━ */}
      <HeroCover onSignup={() => openAuth('signup')} onHowItWorks={scrollToHow} />

      {/* ━━━ PRESS TICKER ━━━ */}
      <PressTicker />

      {/* ━━━ AT-A-GLANCE STRIP — count-up figures ━━━ */}
      <AtAGlance />

      {/* ━━━ HOW IT WORKS — scroll-pinned plates ━━━ */}
      <ProcessReel plates={PLATES} />

      {/* ━━━ THE DISTRIBUTION ━━━ */}
      <DistributionStrip />

      {/* ━━━ DOSSIER SPECIMEN ━━━ */}
      <section
        id="dossier"
        style={{ borderBottom: '0.5px solid var(--border-color)', background: 'var(--paper)' }}
      >
        <div style={{ maxWidth: 1280, margin: '0 auto', padding: '120px 48px' }}>
          <div
            style={{
              display: 'grid',
              gridTemplateColumns: '220px 1fr',
              gap: 72,
              alignItems: 'flex-start',
            }}
          >
            <div style={{ position: 'sticky', top: 130 }}>
              <span
                className="font-serif numeral"
                style={{ fontSize: 44, color: 'var(--ink-tertiary)', fontStyle: 'italic' }}
              >
                IV
              </span>
              <div
                style={{
                  marginTop: 18,
                  fontSize: 10,
                  letterSpacing: '0.3em',
                  textTransform: 'uppercase',
                  color: 'var(--ink-secondary)',
                  fontWeight: 600,
                }}
              >
                The Index
              </div>
              <div style={{ width: 24, height: 2, background: 'var(--red)', margin: '14px 0' }} />
              <p
                className="font-serif"
                style={{
                  fontSize: 14,
                  fontStyle: 'italic',
                  fontWeight: 600,
                  color: 'var(--ink-secondary)',
                  lineHeight: 1.55,
                  maxWidth: 200,
                }}
              >
                Every dossier you file is stamped, dated, and put on the ledger — exactly like the
                four below.
              </p>
            </div>

            <div>
              <Reveal>
                <SectionKicker label="A Specimen Index" />
                <h2
                  className="font-serif"
                  style={{
                    fontSize: 'clamp(36px, 4vw, 60px)',
                    fontWeight: 900,
                    fontStyle: 'italic',
                    color: 'var(--ink)',
                    lineHeight: 1.02,
                    letterSpacing: '-0.03em',
                    marginBottom: 48,
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

      {/* ━━━ FROM THE EDITOR ━━━ */}
      <EditorsNote />

      {/* ━━━ LETTERS TO THE EDITOR ━━━ */}
      <LettersSection />

      {/* ━━━ SUBSCRIPTIONS ━━━ */}
      <SubscriptionsSection onSignup={() => openAuth('signup')} />

      {/* ━━━ FINAL CTA ━━━ */}
      <FinalCTA onSignup={() => openAuth('signup')} />

      {/* ━━━ COLOPHON FOOTER ━━━ */}
      <footer style={{ background: 'var(--ink)', borderTop: '0.5px solid rgba(242,236,224,0.08)' }}>
        <div
          style={{
            maxWidth: 1280,
            margin: '0 auto',
            padding: '64px 48px 28px',
            display: 'grid',
            gridTemplateColumns: '1.6fr 1fr 1fr 1fr',
            gap: 40,
          }}
        >
          <div>
            <div
              className="font-serif"
              style={{
                fontSize: 30,
                fontWeight: 900,
                fontStyle: 'italic',
                color: 'var(--paper)',
                letterSpacing: '-0.03em',
              }}
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
          ].map((col) => (
            <div key={col.h}>
              <div
                style={{
                  fontSize: 9,
                  letterSpacing: '0.3em',
                  textTransform: 'uppercase',
                  color: 'rgba(242,236,224,0.45)',
                  marginBottom: 16,
                  fontWeight: 600,
                }}
              >
                {col.h}
              </div>
              {col.items.map((it) => (
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
                  onMouseEnter={(e) => (e.currentTarget.style.color = 'var(--red)')}
                  onMouseLeave={(e) => (e.currentTarget.style.color = 'rgba(242,236,224,0.65)')}
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
            letterSpacing: '0.2em',
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

/* ─────────────────────────────────────────────────────────────── */
/*                         AT-A-GLANCE                              */
/* ─────────────────────────────────────────────────────────────── */
const GLANCE = [
  { kicker: 'Press · Live', to: 1420812, tail: 'scenarios at press' },
  { kicker: 'Today · Filed', to: 113, tail: 'dossiers archived' },
  { kicker: 'Cohort', to: 10000, tail: 'synthetic readers per run' },
  { kicker: 'Filed', to: 2, tail: 'minutes from idea to report', suffix: ' min' },
] as const

function AtAGlance() {
  return (
    <section style={{ borderBottom: '0.5px solid var(--border-color)', background: 'var(--paper)' }}>
      <div
        style={{
          maxWidth: 1280,
          margin: '0 auto',
          padding: '64px 48px',
          display: 'grid',
          gridTemplateColumns: 'repeat(4, 1fr)',
          borderTop: '0.5px solid var(--border-color)',
          borderBottom: '0.5px solid var(--border-color)',
        }}
      >
        {GLANCE.map((g, i) => (
          <Reveal key={g.kicker} delay={i * 0.08} y={18}>
            <div
              style={{
                padding: '36px 32px',
                borderRight:
                  i < GLANCE.length - 1 ? '0.5px solid var(--border-color)' : 'none',
                minHeight: 180,
                display: 'flex',
                flexDirection: 'column',
                justifyContent: 'space-between',
                position: 'relative',
                overflow: 'hidden',
              }}
            >
              <div
                style={{
                  fontSize: 9,
                  letterSpacing: '0.3em',
                  textTransform: 'uppercase',
                  color: 'var(--red)',
                  fontWeight: 600,
                  display: 'flex',
                  alignItems: 'center',
                  gap: 10,
                }}
              >
                <span
                  aria-hidden
                  style={{ width: 18, height: 1, background: 'var(--red)', display: 'inline-block' }}
                />
                {g.kicker}
              </div>

              <div
                className="font-serif numeral"
                style={{
                  fontSize: 'clamp(44px, 4.6vw, 72px)',
                  color: 'var(--ink)',
                  letterSpacing: '-0.035em',
                  lineHeight: 1,
                  fontStyle: 'italic',
                  fontWeight: 900,
                }}
              >
                <CountUp to={g.to} suffix={'suffix' in g ? (g as { suffix: string }).suffix : ''} />
              </div>

              <div
                style={{
                  fontSize: 11,
                  color: 'var(--ink-secondary)',
                  letterSpacing: '0.14em',
                  textTransform: 'uppercase',
                  fontWeight: 500,
                }}
              >
                {g.tail}
              </div>
            </div>
          </Reveal>
        ))}
      </div>
    </section>
  )
}

/* ─────────────────────────────────────────────────────────────── */
/*                        DISTRIBUTION STRIP                        */
/* ─────────────────────────────────────────────────────────────── */
/**
 * Distribution palette — each bucket has its own identity so hover
 * reinforces the segment instead of washing every non-accent fill to ink.
 *   rest : base (unhovered) fill on the bar
 *   hover: darker sibling used when the segment is hovered
 *   label: colour used for the legend word in both states
 */
const DISTRIBUTION = [
  {
    label: 'Dies fast',
    sub: 'runway gone inside 90 days',
    pct: 14,
    rest: 'rgba(26,23,20,0.08)',
    hover: 'rgba(26,23,20,0.55)',
    label_rest: 'var(--ink-secondary)',
    label_hover: 'rgba(26,23,20,0.78)',
  },
  {
    label: 'Quiet death',
    sub: 'grows, then stalls without recovering',
    pct: 23,
    rest: 'rgba(90,78,66,0.18)',
    hover: 'rgba(90,78,66,0.62)',
    label_rest: 'var(--ink-secondary)',
    label_hover: 'rgba(90,78,66,0.92)',
  },
  {
    label: 'Pivots',
    sub: 'the idea survives; the shape changes',
    pct: 31,
    accent: true,
    rest: 'rgba(192,57,43,0.16)',
    hover: 'var(--red)',
    label_rest: 'var(--red)',
    label_hover: 'var(--red)',
  },
  {
    label: 'Survives',
    sub: 'modest, durable, compounding',
    pct: 22,
    rest: 'rgba(120,110,72,0.22)',
    hover: 'rgba(120,110,72,0.72)',
    label_rest: 'var(--ink-secondary)',
    label_hover: 'rgba(120,110,72,0.96)',
  },
  {
    label: 'Scales',
    sub: 'the distribution you are betting on',
    pct: 10,
    rest: 'rgba(58,90,72,0.26)',
    hover: 'rgba(58,90,72,0.82)',
    label_rest: 'var(--ink-secondary)',
    label_hover: 'rgba(58,90,72,1)',
  },
] as const

function DistributionStrip() {
  const [hover, setHover] = useState<number | null>(null)
  return (
    <section style={{ borderBottom: '0.5px solid var(--border-color)', background: 'var(--paper-dark)' }}>
      <div style={{ maxWidth: 1280, margin: '0 auto', padding: '120px 48px 104px' }}>
        <div
          style={{
            display: 'grid',
            gridTemplateColumns: '220px 1fr',
            gap: 72,
            alignItems: 'flex-start',
          }}
        >
          <div style={{ position: 'sticky', top: 130 }}>
            <span
              className="font-serif numeral"
              style={{ fontSize: 44, color: 'var(--ink-tertiary)', fontStyle: 'italic' }}
            >
              V
            </span>
            <div
              style={{
                marginTop: 18,
                fontSize: 10,
                letterSpacing: '0.3em',
                textTransform: 'uppercase',
                color: 'var(--ink-secondary)',
                fontWeight: 600,
              }}
            >
              The Distribution
            </div>
            <div style={{ width: 24, height: 2, background: 'var(--red)', margin: '14px 0' }} />
            <p
              className="font-serif"
              style={{
                fontSize: 14,
                fontStyle: 'italic',
                fontWeight: 600,
                color: 'var(--ink-secondary)',
                lineHeight: 1.55,
                maxWidth: 200,
              }}
            >
              We do not hand you a verdict. We hand you the shape of every future your idea could
              walk into.
            </p>
          </div>

          <div>
            <Reveal>
              <SectionKicker label="The shape of a hundred futures" />
              <h2
                className="font-serif"
                style={{
                  fontSize: 'clamp(36px, 4vw, 60px)',
                  fontWeight: 900,
                  fontStyle: 'italic',
                  color: 'var(--ink)',
                  lineHeight: 1.02,
                  letterSpacing: '-0.03em',
                  marginBottom: 56,
                  maxWidth: 680,
                }}
              >
                Every idea has a shape.{' '}
                <span style={{ color: 'var(--red)' }}>We show you yours.</span>
              </h2>
            </Reveal>

            <Reveal delay={0.1}>
              <div
                style={{
                  position: 'relative',
                  height: 64,
                  border: '0.5px solid var(--ink)',
                  display: 'flex',
                  background: 'var(--paper)',
                }}
                onMouseLeave={() => setHover(null)}
              >
                {DISTRIBUTION.map((row, i) => {
                  const isHover = hover === i
                  return (
                    <motion.div
                      key={row.label}
                      initial={{ width: 0 }}
                      whileInView={{ width: `${row.pct}%` }}
                      viewport={{ once: true, margin: '-40px' }}
                      transition={{
                        duration: 1,
                        delay: 0.15 + i * 0.1,
                        ease: [0.2, 0.7, 0.2, 1],
                      }}
                      onMouseEnter={() => setHover(i)}
                      style={{
                        position: 'relative',
                        borderRight:
                          i < DISTRIBUTION.length - 1 ? '0.5px solid var(--ink)' : 'none',
                        background: isHover ? row.hover : row.rest,
                        transition: 'background 260ms ease',
                        cursor: 'default',
                      }}
                    >
                      <AnimatePresence>
                        {isHover && (
                          <motion.div
                            key="whisk"
                            initial={{ opacity: 0, y: 6 }}
                            animate={{ opacity: 1, y: 0 }}
                            exit={{ opacity: 0, y: 6 }}
                            transition={{ duration: 0.22 }}
                            style={{
                              position: 'absolute',
                              top: -46,
                              left: '50%',
                              transform: 'translateX(-50%)',
                              whiteSpace: 'nowrap',
                              textAlign: 'center',
                              fontFamily:
                                "var(--font-serif, 'Playfair Display', Georgia, serif)",
                              fontStyle: 'italic',
                              fontWeight: 800,
                              fontSize: 28,
                              letterSpacing: '-0.02em',
                              color: row.label_hover,
                            }}
                          >
                            {row.pct}
                            <span style={{ fontSize: 14, opacity: 0.5 }}>%</span>
                          </motion.div>
                        )}
                      </AnimatePresence>
                    </motion.div>
                  )
                })}
              </div>
            </Reveal>

            <div style={{ display: 'flex', marginTop: 20 }}>
              {DISTRIBUTION.map((row, i) => {
                const isHover = hover === i
                return (
                  <div
                    key={row.label}
                    onMouseEnter={() => setHover(i)}
                    onMouseLeave={() => setHover(null)}
                    style={{
                      flexBasis: `${row.pct}%`,
                      flexGrow: 0,
                      flexShrink: 0,
                      paddingRight: 12,
                      borderTop: `0.5px solid ${
                        isHover ? row.label_hover : 'var(--border-color)'
                      }`,
                      paddingTop: 14,
                      minWidth: 0,
                      transition: 'border-color 220ms ease',
                    }}
                  >
                    <div
                      style={{
                        fontSize: 11,
                        letterSpacing: '0.14em',
                        textTransform: 'uppercase',
                        fontWeight: 600,
                        color: isHover ? row.label_hover : row.label_rest,
                        transition: 'color 220ms ease',
                        marginBottom: 6,
                        whiteSpace: 'nowrap',
                        overflow: 'hidden',
                        textOverflow: 'ellipsis',
                      }}
                    >
                      {row.label}
                    </div>
                    <div
                      style={{
                        fontSize: 11,
                        color: 'var(--ink-tertiary)',
                        lineHeight: 1.5,
                      }}
                    >
                      {row.sub}
                    </div>
                  </div>
                )
              })}
            </div>

            <div
              style={{
                marginTop: 40,
                fontSize: 10,
                letterSpacing: '0.3em',
                textTransform: 'uppercase',
                color: 'var(--ink-tertiary)',
                fontVariantNumeric: 'tabular-nums',
                fontWeight: 600,
              }}
            >
              Specimen · Urban D2C cohort · 10,000 agents · 2,430 paths
            </div>
          </div>
        </div>
      </div>
    </section>
  )
}

/* ─────────────────────────────────────────────────────────────── */
/*                         EDITOR'S NOTE                           */
/* ─────────────────────────────────────────────────────────────── */
function EditorsNote() {
  return (
    <section style={{ borderBottom: '0.5px solid var(--border-color)', background: 'var(--paper)' }}>
      <div style={{ maxWidth: 1100, margin: '0 auto', padding: '120px 48px 104px' }}>
        <Reveal>
          <div style={{ textAlign: 'center', marginBottom: 56 }}>
            <div
              style={{
                fontSize: 10,
                letterSpacing: '0.3em',
                textTransform: 'uppercase',
                color: 'var(--red)',
                fontWeight: 600,
                marginBottom: 18,
              }}
            >
              From the editor · April 2026
            </div>
            <h2
              className="font-serif"
              style={{
                fontSize: 'clamp(32px, 3.6vw, 54px)',
                fontStyle: 'italic',
                fontWeight: 800,
                color: 'var(--ink)',
                lineHeight: 1.12,
                letterSpacing: '-0.025em',
                maxWidth: 840,
                margin: '0 auto',
              }}
            >
              Why we are printing a simulation <br />
              instead of a <span style={{ color: 'var(--red)' }}>startup advice column</span>.
            </h2>
          </div>
        </Reveal>

        <Reveal delay={0.08}>
          <div
            className="col-rule dropcap"
            style={{
              columnCount: 2,
              columnGap: 48,
              maxWidth: 860,
              margin: '0 auto',
              fontFamily: "var(--font-serif, 'Playfair Display', Georgia, serif)",
              fontSize: 17,
              lineHeight: 1.75,
              color: 'var(--ink)',
              fontWeight: 300,
              letterSpacing: '-0.005em',
              textAlign: 'justify',
              hyphens: 'auto',
            }}
          >
            <p style={{ marginBottom: 16 }}>
              The honest founder does not need another piece of advice. They have enough. They have
              a friend who built a SaaS tool in 2019, an uncle with an opinion about packaging, a
              newsletter with eleven frameworks, and a podcast that told them to just ship.
            </p>
            <p style={{ marginBottom: 16 }}>
              What they do not have is a room full of a thousand quiet strangers who will look at
              their idea and, without flattery, tell them where it will break. That room is
              expensive. It takes twelve months to build and a lot of money to keep in the dark.
            </p>
            <p style={{ marginBottom: 16 }}>
              We built the room and put a door on it. The door is the simulation. On the other
              side, a cohort of synthetic readers — priced, placed, suspicious, bored, loyal, or
              bored-and-loyal — vote on your pricing, your channel, your timing, and your story.
              They do not flatter you.
            </p>
            <p>
              We print what they said. You read the autopsy before the burial. Then you decide
              whether to build. That is the whole magazine, in a sentence.
            </p>
          </div>
        </Reveal>

        {/* Signature rule — draws in on view */}
        <Reveal delay={0.12}>
          <div
            style={{
              maxWidth: 860,
              margin: '48px auto 0',
              display: 'flex',
              alignItems: 'center',
              gap: 18,
              justifyContent: 'flex-end',
              fontSize: 10,
              letterSpacing: '0.3em',
              textTransform: 'uppercase',
              color: 'var(--ink-tertiary)',
              fontWeight: 600,
            }}
          >
            <motion.span
              initial={{ scaleX: 0 }}
              whileInView={{ scaleX: 1 }}
              viewport={{ once: true }}
              transition={{ duration: 0.9, ease: [0.2, 0.7, 0.2, 1] }}
              style={{
                display: 'inline-block',
                width: 72,
                height: 0.5,
                background: 'var(--border-strong)',
                transformOrigin: 'left',
              }}
            />
            <span
              className="font-serif"
              style={{
                fontStyle: 'italic',
                fontSize: 18,
                letterSpacing: 0,
                textTransform: 'none',
                color: 'var(--ink)',
                fontWeight: 700,
              }}
            >
              The Editor
            </span>
            <span>TheCee · Bengaluru · IST</span>
          </div>
        </Reveal>
      </div>
    </section>
  )
}

/* ─────────────────────────────────────────────────────────────── */
/*                        LETTERS SECTION                           */
/* ─────────────────────────────────────────────────────────────── */
function LettersSection() {
  return (
    <section
      id="letters"
      style={{ borderBottom: '0.5px solid var(--border-color)', background: 'var(--paper-dark)' }}
    >
      <div style={{ maxWidth: 1280, margin: '0 auto', padding: '120px 48px' }}>
        <Reveal>
          <SectionKicker label="Letters to the Editor" />
          <h2
            className="font-serif"
            style={{
              fontSize: 'clamp(36px, 4vw, 60px)',
              fontWeight: 900,
              fontStyle: 'italic',
              color: 'var(--ink)',
              lineHeight: 1.02,
              letterSpacing: '-0.03em',
              marginBottom: 64,
              maxWidth: 760,
            }}
          >
            Built for people who <span style={{ color: 'var(--red)' }}>cannot</span> afford to guess.
          </h2>
        </Reveal>

        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(2, 1fr)' }}>
          {LETTERS.map((l, i) => (
            <Reveal key={l.title} delay={i * 0.08} y={36}>
              <LetterCard letter={l} edgeRight={i % 2 === 0} />
            </Reveal>
          ))}
        </div>
      </div>
    </section>
  )
}

function LetterCard({
  letter,
  edgeRight,
}: {
  letter: (typeof LETTERS)[number]
  edgeRight: boolean
}) {
  const [tilt, setTilt] = useState({ rx: 0, ry: 0 })
  const [hover, setHover] = useState(false)
  const onMove = (e: React.MouseEvent<HTMLElement>) => {
    const r = e.currentTarget.getBoundingClientRect()
    const px = (e.clientX - r.left) / r.width - 0.5
    const py = (e.clientY - r.top) / r.height - 0.5
    setTilt({ rx: -py * 4, ry: px * 4 })
  }
  const reset = () => {
    setTilt({ rx: 0, ry: 0 })
  }
  return (
    <article
      onMouseMove={onMove}
      onMouseLeave={() => {
        reset()
        setHover(false)
      }}
      onMouseEnter={() => setHover(true)}
      style={{
        padding: 44,
        borderTop: '0.5px solid var(--border-color)',
        borderRight: edgeRight ? '0.5px solid var(--border-color)' : 'none',
        background: hover ? 'var(--paper)' : 'var(--paper-dark)',
        transform: `perspective(900px) rotateX(${tilt.rx}deg) rotateY(${tilt.ry}deg)`,
        transformStyle: 'preserve-3d' as const,
        transition: 'background 0.3s ease',
        position: 'relative',
      }}
    >
      <div
        style={{
          display: 'inline-block',
          fontSize: 9,
          color: 'var(--red)',
          letterSpacing: '0.24em',
          textTransform: 'uppercase',
          fontWeight: 600,
          borderLeft: '2px solid var(--red)',
          paddingLeft: 10,
          marginBottom: 24,
        }}
      >
        {letter.tag}
      </div>
      <h3
        className="font-serif"
        style={{
          fontSize: 26,
          fontWeight: 800,
          fontStyle: 'italic',
          color: 'var(--ink)',
          lineHeight: 1.2,
          marginBottom: 14,
          letterSpacing: '-0.01em',
        }}
      >
        {letter.title}
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
        {letter.body}
      </p>
      <div
        style={{
          marginTop: 24,
          paddingTop: 14,
          borderTop: '0.5px solid var(--border-color)',
          fontSize: 10,
          letterSpacing: '0.2em',
          textTransform: 'uppercase',
          color: 'var(--ink-tertiary)',
          fontWeight: 600,
        }}
      >
        — {letter.sig}
      </div>
    </article>
  )
}

/* ─────────────────────────────────────────────────────────────── */
/*                     SUBSCRIPTIONS                                */
/* ─────────────────────────────────────────────────────────────── */
function SubscriptionsSection({ onSignup }: { onSignup: () => void }) {
  return (
    <section id="pricing" style={{ borderBottom: '0.5px solid var(--border-color)' }}>
      <div style={{ maxWidth: 1280, margin: '0 auto', padding: '120px 48px' }}>
        <Reveal>
          <SectionKicker label="Subscriptions · The Press Tiers" />
          <h2
            className="font-serif"
            style={{
              fontSize: 'clamp(36px, 4vw, 60px)',
              fontWeight: 900,
              fontStyle: 'italic',
              color: 'var(--ink)',
              lineHeight: 1.02,
              letterSpacing: '-0.03em',
              marginBottom: 64,
              maxWidth: 760,
            }}
          >
            Subscribe to the <span style={{ color: 'var(--red)' }}>broadsheet</span>.
          </h2>
        </Reveal>

        <div
          style={{
            display: 'grid',
            gridTemplateColumns: 'repeat(3, 1fr)',
            border: '0.5px solid var(--ink)',
          }}
        >
          {TIERS.map((t, i) => (
            <Reveal key={t.name} delay={i * 0.1}>
              <TierCard tier={t} edgeRight={i < TIERS.length - 1} onSignup={onSignup} />
            </Reveal>
          ))}
        </div>
      </div>
    </section>
  )
}

function TierCard({
  tier,
  edgeRight,
  onSignup,
}: {
  tier: (typeof TIERS)[number]
  edgeRight: boolean
  onSignup: () => void
}) {
  const [hover, setHover] = useState(false)
  const ink: CSSProperties = {
    background: tier.accent ? 'var(--ink)' : 'var(--paper)',
    color: tier.accent ? 'var(--paper)' : 'var(--ink)',
  }
  return (
    <div
      onMouseEnter={() => setHover(true)}
      onMouseLeave={() => setHover(false)}
      style={{
        ...ink,
        padding: 40,
        borderRight: edgeRight ? '0.5px solid var(--border-color)' : 'none',
        minHeight: 480,
        display: 'flex',
        flexDirection: 'column',
        position: 'relative',
        overflow: 'hidden',
      }}
    >
      {/* Ink-fill wipe on hover (for non-accent tiers only) */}
      {!tier.accent && (
        <motion.span
          aria-hidden
          initial={false}
          animate={{ scaleY: hover ? 1 : 0 }}
          transition={{ duration: 0.5, ease: [0.2, 0.7, 0.2, 1] }}
          style={{
            position: 'absolute',
            inset: 0,
            background: 'var(--ink)',
            transformOrigin: 'bottom',
            zIndex: 0,
          }}
        />
      )}

      {/* "Editor's pick" press stamp on the featured tier */}
      {tier.accent && (
        <div
          style={{
            position: 'absolute',
            top: 24,
            right: 24,
            width: 92,
            height: 92,
            border: '1px solid var(--red)',
            borderRadius: '50%',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            transform: 'rotate(-8deg)',
            color: 'var(--red)',
            opacity: 0.9,
          }}
        >
          <div style={{ textAlign: 'center', lineHeight: 1.1 }}>
            <div
              className="font-serif"
              style={{ fontStyle: 'italic', fontWeight: 800, fontSize: 16 }}
            >
              Editor&rsquo;s
            </div>
            <div
              style={{
                fontSize: 8,
                letterSpacing: '0.24em',
                textTransform: 'uppercase',
                fontWeight: 600,
                marginTop: 2,
              }}
            >
              Pick
            </div>
          </div>
        </div>
      )}

      <motion.div
        animate={{ color: !tier.accent && hover ? 'var(--paper)' : undefined }}
        transition={{ duration: 0.3 }}
        style={{ position: 'relative', zIndex: 1, display: 'flex', flexDirection: 'column', flex: 1 }}
      >
        <div
          style={{
            fontSize: 10,
            letterSpacing: '0.3em',
            textTransform: 'uppercase',
            color: 'var(--red)',
            fontWeight: 600,
            marginBottom: 14,
          }}
        >
          {tier.note}
        </div>
        <h3
          className="font-serif"
          style={{
            fontSize: 32,
            fontWeight: 900,
            fontStyle: 'italic',
            letterSpacing: '-0.03em',
            marginBottom: 20,
          }}
        >
          {tier.name}
        </h3>
        <div
          className="font-serif numeral"
          style={{
            fontSize: 60,
            letterSpacing: '-0.04em',
            lineHeight: 1,
            fontStyle: 'italic',
            fontWeight: 900,
          }}
        >
          {tier.price}
        </div>
        <div
          style={{
            fontSize: 10,
            letterSpacing: '0.22em',
            textTransform: 'uppercase',
            opacity: 0.6,
            marginTop: 6,
            marginBottom: 30,
            fontWeight: 600,
          }}
        >
          {tier.sub}
        </div>

        <ul style={{ listStyle: 'none', padding: 0, margin: 0, flex: 1 }}>
          {tier.bullets.map((b) => (
            <li
              key={b}
              style={{
                padding: '10px 0',
                borderBottom: tier.accent
                  ? '0.5px solid rgba(242,236,224,0.1)'
                  : !tier.accent && hover
                  ? '0.5px solid rgba(242,236,224,0.15)'
                  : '0.5px solid var(--border-color)',
                fontSize: 13,
                display: 'flex',
                alignItems: 'center',
                gap: 12,
                opacity: 0.85,
              }}
            >
              <span
                style={{
                  width: 6,
                  height: 6,
                  background: 'var(--red)',
                  display: 'inline-block',
                  flexShrink: 0,
                }}
              />
              {b}
            </li>
          ))}
        </ul>

        <button
          type="button"
          onClick={onSignup}
          style={{
            marginTop: 28,
            background: tier.accent ? 'var(--red)' : 'var(--ink)',
            color: 'var(--paper)',
            border: 'none',
            padding: '14px 22px',
            fontSize: 11,
            letterSpacing: '0.18em',
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
          onMouseEnter={(e) => {
            ;(e.currentTarget as HTMLButtonElement).style.background = tier.accent
              ? '#a93226'
              : 'var(--red)'
          }}
          onMouseLeave={(e) => {
            ;(e.currentTarget as HTMLButtonElement).style.background = tier.accent
              ? 'var(--red)'
              : 'var(--ink)'
          }}
        >
          {tier.cta} <ArrowRight size={12} />
        </button>
      </motion.div>
    </div>
  )
}

/* ─────────────────────────────────────────────────────────────── */
/*                          FINAL CTA                               */
/* ─────────────────────────────────────────────────────────────── */
function FinalCTA({ onSignup }: { onSignup: () => void }) {
  const ref = useRef<HTMLElement>(null)
  const [parallaxY, setParallaxY] = useState(0)

  useEffect(() => {
    const el = ref.current
    if (!el) return

    const update = () => {
      const rect = el.getBoundingClientRect()
      const vh = window.innerHeight
      const start = vh * 0.9
      const raw = (start - rect.top) / (rect.height + vh * 0.4)
      setParallaxY(Math.min(1, Math.max(0, raw)))
    }

    update()
    window.addEventListener('scroll', update, { passive: true })
    window.addEventListener('resize', update)
    return () => {
      window.removeEventListener('scroll', update)
      window.removeEventListener('resize', update)
    }
  }, [])

  const yPx = 40 - 80 * parallaxY

  return (
    <section
      ref={ref}
      style={{
        background: 'var(--ink)',
        borderBottom: '3px solid var(--ink)',
        position: 'relative',
        overflow: 'hidden',
      }}
    >
      {/* Giant faint serif watermark */}
      <div
        aria-hidden
        style={{
          position: 'absolute',
          inset: 0,
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          pointerEvents: 'none',
          transform: `translateY(${yPx}px)`,
          willChange: 'transform',
        }}
      >
        <span
          className="font-serif"
          style={{
            fontSize: 'clamp(200px, 30vw, 460px)',
            fontStyle: 'italic',
            fontWeight: 900,
            color: 'rgba(242,236,224,0.035)',
            letterSpacing: '-0.06em',
            lineHeight: 1,
            whiteSpace: 'nowrap',
          }}
        >
          TheCee
        </span>
      </div>

      <div
        style={{
          maxWidth: 1280,
          margin: '0 auto',
          padding: '140px 48px',
          display: 'grid',
          gridTemplateColumns: '1.5fr 1fr',
          gap: 80,
          alignItems: 'center',
          position: 'relative',
          zIndex: 1,
        }}
      >
        <Reveal>
          <div style={{ height: 2, width: 28, background: 'var(--red)', marginBottom: 26 }} />
          <h2
            className="font-serif"
            style={{
              fontSize: 'clamp(42px, 5vw, 78px)',
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
              fontSize: 16,
              color: 'rgba(242,236,224,0.55)',
              lineHeight: 1.85,
              marginBottom: 38,
              maxWidth: 500,
              fontWeight: 300,
            }}
          >
            Stop planning. Stop guessing. Start simulating — and know before you build. The press is
            open. Walk into the room.
          </p>
          <MagneticCTA
            onClick={onSignup}
            style={{
              background: 'var(--red)',
              color: '#fff',
              padding: '18px 36px',
              fontSize: 12,
              letterSpacing: '0.2em',
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
                fontSize: 24,
                fontStyle: 'italic',
                fontWeight: 700,
                color: 'var(--paper)',
                lineHeight: 1.45,
                marginBottom: 22,
                opacity: 0.9,
              }}
            >
              &ldquo;Every decision made without simulation is a decision made blind.&rdquo;
            </p>
            <p
              style={{
                fontSize: 10,
                color: 'rgba(242,236,224,0.4)',
                letterSpacing: '0.22em',
                textTransform: 'uppercase',
                fontWeight: 600,
              }}
            >
              — TheCee, 2026
            </p>
          </div>
        </Reveal>
      </div>
    </section>
  )
}
