'use client'

import { useRef, useState, useEffect } from 'react'
import { motion, useScroll, useTransform, AnimatePresence } from 'framer-motion'
import Link from 'next/link'
import { ArrowRight, ArrowUpRight, ChevronDown, Minus } from 'lucide-react'
import SimulationTimeline from '@/components/layout/SimulationTimeline'

/* ─── CONSTANTS ─────────────────────────────────── */
const WORDS = ['startup', 'product', 'idea', 'launch', 'decision']

const STEPS = [
  {
    n: '01',
    title: 'Describe your idea',
    body: 'Write your product or business concept in plain language. No forms, no templates. Just your idea as you see it.',
    kicker: 'Input',
  },
  {
    n: '02',
    title: 'We stress-test it',
    body: 'TheCee runs your idea through thousands of real-world scenarios — different customers, market conditions, and risks you have not considered.',
    kicker: 'Process',
  },
  {
    n: '03',
    title: 'You get clarity',
    body: 'See what will work, what will fail, and the precise changes that shift the odds in your favour — before you spend a single rupee.',
    kicker: 'Output',
  },
]

const WHO = [
  {
    title: 'First-time founders',
    body: 'Launching your first product with limited runway. Know which risks are real before you spend anything.',
    tag: 'Validate before you build',
  },
  {
    title: 'Product managers',
    body: 'Justify your next feature or launch with scenario data instead of opinions in a meeting room.',
    tag: 'Data over opinion',
  },
  {
    title: 'D2C and physical products',
    body: 'Test pricing, channels, and customer response before committing to inventory or manufacturing.',
    tag: 'Test before you manufacture',
  },
  {
    title: 'Side project builders',
    body: 'Find out if your weekend idea is worth your evenings before you invest months into it.',
    tag: 'Know before you commit',
  },
]

const STATS = [
  { value: '10,000+', label: 'Scenarios per simulation run' },
  { value: '< 2 min', label: 'Time to first clear insight' },
  { value: '3×', label: 'Cross-validated by default' },
  { value: '240+', label: 'Founders validated so far' },
]

/* ─── WORD ROTATOR ───────────────────────────────── */
function WordRotator() {
  const [index, setIndex] = useState(0)
  useEffect(() => {
    const t = setInterval(() => setIndex(i => (i + 1) % WORDS.length), 2400)
    return () => clearInterval(t)
  }, [])
  return (
    <span
      className="relative inline-block overflow-hidden"
      style={{ minWidth: '260px', verticalAlign: 'bottom' }}
    >
      <AnimatePresence mode="wait">
        <motion.span
          key={WORDS[index]}
          initial={{ y: 48, opacity: 0 }}
          animate={{ y: 0, opacity: 1 }}
          exit={{ y: -48, opacity: 0 }}
          transition={{ duration: 0.5, ease: [0.76, 0, 0.24, 1] }}
          style={{
            display: 'inline-block',
            color: 'var(--red)',
            fontStyle: 'italic',
          }}
        >
          {WORDS[index]}
        </motion.span>
      </AnimatePresence>
    </span>
  )
}

/* ─── SECTION REVEAL ─────────────────────────────── */
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
      initial={{ opacity: 0, y: 32 }}
      whileInView={{ opacity: 1, y: 0 }}
      viewport={{ once: true, margin: '-60px' }}
      transition={{ duration: 0.8, delay, ease: [0.25, 0.46, 0.45, 0.94] }}
      className={className}
    >
      {children}
    </motion.div>
  )
}

/* ─── SECTION KICKER ─────────────────────────────── */
function SectionKicker({ label }: { label: string }) {
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: '12px', marginBottom: '32px' }}>
      <div style={{ height: '2px', width: '20px', background: 'var(--red)', flexShrink: 0 }} />
      <span style={{
        fontSize: '9px',
        color: 'var(--red)',
        letterSpacing: '0.22em',
        textTransform: 'uppercase',
        fontWeight: 500,
      }}>
        {label}
      </span>
    </div>
  )
}

/* ─── MAIN PAGE ──────────────────────────────────── */
export default function LandingPage() {
  const heroRef = useRef<HTMLDivElement>(null)
  const { scrollYProgress } = useScroll({
    target: heroRef,
    offset: ['start start', 'end start'],
  })
  const heroOpacity = useTransform(scrollYProgress, [0, 0.6], [1, 0])
  const heroY = useTransform(scrollYProgress, [0, 1], [0, 40])
  const [menuOpen, setMenuOpen] = useState(false)
  const [isAuthed, setIsAuthed] = useState(false)
  const [userEmail, setUserEmail] = useState('')
  const [profileOpen, setProfileOpen] = useState(false)

  useEffect(() => {
    const auth = sessionStorage.getItem('thecee-auth')
    const email = sessionStorage.getItem('thecee-user-email') ?? ''
    if (auth === '1') {
      setIsAuthed(true)
      setUserEmail(email)
    }
  }, [])

  const signOut = () => {
    sessionStorage.removeItem('thecee-auth')
    sessionStorage.removeItem('thecee-user-email')
    setIsAuthed(false)
    setUserEmail('')
    setProfileOpen(false)
    setMenuOpen(false)
  }

  return (
    <div style={{ background: 'var(--paper)', minHeight: '100vh', position: 'relative' }}>

      {/* ━━━ HEADER / NAVBAR ━━━ */}
      <motion.header
        initial={{ opacity: 0 }}
        animate={{ opacity: 1 }}
        transition={{ duration: 0.6 }}
        style={{ borderBottom: '3px solid var(--ink)', position: 'sticky', top: 0, zIndex: 50, background: 'var(--paper)' }}
      >
        {/* Top strip — centre column is truly centred (equal 1fr side columns) */}
        <div style={{
          borderBottom: '0.5px solid var(--border)',
          padding: '6px 48px',
          display: 'grid',
          gridTemplateColumns: '1fr auto 1fr',
          alignItems: 'center',
        }}>
          <p style={{ fontSize: '10px', color: 'var(--ink-secondary)', letterSpacing: '0.15em', textTransform: 'uppercase', justifySelf: 'start' }}>
            Simulation Intelligence Platform
          </p>
          <p style={{ fontSize: '10px', color: 'var(--ink-secondary)', letterSpacing: '0.12em', textAlign: 'center', justifySelf: 'center' }}>
            Est. 2026 — Early Access
          </p>
          <p style={{ fontSize: '10px', color: 'var(--ink-secondary)', letterSpacing: '0.12em', justifySelf: 'end' }}>
            thecee.app
          </p>
        </div>

        {/* Main nav row */}
        <div style={{
          padding: '16px 48px',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          position: 'relative',
        }}>
          {/* Hamburger button */}
          <button
            type="button"
            onClick={() => setMenuOpen(true)}
            style={{
              background: 'none',
              border: 'none',
              cursor: 'pointer',
              padding: '4px',
              display: 'flex',
              flexDirection: 'column',
              gap: '5px',
              width: '28px',
            }}
            aria-label="Open menu"
          >
            {[0, 1, 2].map(i => (
              <div key={i} style={{
                width: i === 2 ? '16px' : '24px',
                height: '1.5px',
                background: 'var(--ink)',
                transition: 'width 0.3s ease',
              }} />
            ))}
          </button>

          {/* Masthead — centred */}
          <div style={{ textAlign: 'center', position: 'absolute', left: '50%', transform: 'translateX(-50%)' }}>
            <div className="font-serif" style={{
              fontSize: '36px',
              fontWeight: 900,
              color: 'var(--ink)',
              letterSpacing: '-0.04em',
              lineHeight: 1,
              fontStyle: 'italic',
            }}>
              TheCee
            </div>
          </div>

          {/* Right side — auth CTAs hidden when signed in (session hint) */}
          <div style={{ display: 'flex', gap: '20px', alignItems: 'center', minWidth: '140px', justifyContent: 'flex-end' }}>
            {!isAuthed && (
              <>
                <Link href="/login"
                  style={{ fontSize: '11px', color: 'var(--ink-secondary)', letterSpacing: '0.08em', textTransform: 'uppercase', textDecoration: 'none' }}
                  onMouseEnter={e => (e.currentTarget.style.color = 'var(--ink)')}
                  onMouseLeave={e => (e.currentTarget.style.color = 'var(--ink-secondary)')}
                >
                  Sign in
                </Link>
                <Link href="/signup"
                  style={{
                    fontSize: '11px',
                    color: 'var(--paper)',
                    background: 'var(--ink)',
                    padding: '8px 18px',
                    letterSpacing: '0.08em',
                    textTransform: 'uppercase',
                    textDecoration: 'none',
                    fontWeight: 500,
                    display: 'flex',
                    alignItems: 'center',
                    gap: '6px',
                  }}
                >
                  Get started <ArrowRight size={11} />
                </Link>
              </>
            )}
          </div>
        </div>
      </motion.header>

      <AnimatePresence>
        {menuOpen && (
          <motion.div
            key="menu-backdrop"
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
        )}
        {menuOpen && (
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
              width: '360px',
              background: 'var(--ink)',
              zIndex: 100,
              display: 'flex',
              flexDirection: 'column',
              padding: '0',
              overflowY: 'auto',
            }}
          >
              {/* Drawer header */}
              <div style={{
                padding: '24px 36px',
                borderBottom: '0.5px solid rgba(242,236,224,0.08)',
                display: 'flex',
                justifyContent: 'space-between',
                alignItems: 'center',
              }}>
                <span className="font-serif" style={{
                  fontSize: '22px',
                  fontWeight: 900,
                  fontStyle: 'italic',
                  color: 'var(--paper)',
                  letterSpacing: '-0.03em',
                }}>
                  TheCee
                </span>
                <button
                  type="button"
                  onClick={() => setMenuOpen(false)}
                  style={{
                    background: 'none',
                    border: 'none',
                    cursor: 'pointer',
                    padding: '6px',
                    color: 'rgba(242,236,224,0.4)',
                    fontSize: '20px',
                    lineHeight: 1,
                    display: 'flex',
                    alignItems: 'center',
                  }}
                  aria-label="Close menu"
                >
                  ✕
                </button>
              </div>

              {/* Nav links */}
              <nav style={{ padding: '16px 0', flex: 1 }}>
                {[
                  { label: 'How it works', href: '#how' },
                  { label: 'Use cases', href: '#who' },
                  { label: 'Pricing', href: '#pricing' },
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
                      fontSize: '13px',
                      letterSpacing: '0.06em',
                      textTransform: 'uppercase',
                      fontWeight: 400,
                      transition: 'color 0.2s',
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
                    <motion.button
                      type="button"
                      initial={{ opacity: 0, x: -20 }}
                      animate={{ opacity: 1, x: 0 }}
                      transition={{ delay: 0.1 + 3 * 0.07, duration: 0.35 }}
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
                        fontSize: '13px',
                        letterSpacing: '0.06em',
                        textTransform: 'uppercase',
                        fontWeight: 400,
                        fontFamily: 'inherit',
                        textAlign: 'left',
                        transition: 'color 0.2s',
                      }}
                      onMouseEnter={e => (e.currentTarget.style.color = 'var(--paper)')}
                      onMouseLeave={e => (e.currentTarget.style.color = 'rgba(242,236,224,0.7)')}
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
                    </motion.button>
                    <AnimatePresence>
                      {profileOpen && (
                        <motion.div
                          key="profile-panel"
                          initial={{ height: 0, opacity: 0 }}
                          animate={{ height: 'auto', opacity: 1 }}
                          exit={{ height: 0, opacity: 0 }}
                          transition={{ duration: 0.25 }}
                          style={{ overflow: 'hidden', borderBottom: '0.5px solid rgba(242,236,224,0.06)' }}
                        >
                          <div style={{ padding: '16px 36px 20px', background: 'rgba(242,236,224,0.04)' }}>
                            <p style={{ fontSize: '9px', letterSpacing: '0.18em', textTransform: 'uppercase', color: 'rgba(242,236,224,0.35)', marginBottom: '8px' }}>
                              Signed in as
                            </p>
                            <p style={{ fontSize: '13px', color: 'var(--paper)', marginBottom: '16px', wordBreak: 'break-all' }}>
                              {userEmail || '—'}
                            </p>
                            <button
                              type="button"
                              onClick={signOut}
                              style={{
                                fontSize: '11px',
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
                  <motion.a
                    href="/login"
                    initial={{ opacity: 0, x: -20 }}
                    animate={{ opacity: 1, x: 0 }}
                    transition={{ delay: 0.1 + 3 * 0.07, duration: 0.35 }}
                    onClick={() => setMenuOpen(false)}
                    style={{
                      display: 'flex',
                      justifyContent: 'space-between',
                      alignItems: 'center',
                      padding: '18px 36px',
                      borderBottom: '0.5px solid rgba(242,236,224,0.06)',
                      textDecoration: 'none',
                      color: 'rgba(242,236,224,0.7)',
                      fontSize: '13px',
                      letterSpacing: '0.06em',
                      textTransform: 'uppercase',
                      fontWeight: 400,
                      transition: 'color 0.2s',
                    }}
                    onMouseEnter={e => (e.currentTarget.style.color = 'var(--paper)')}
                    onMouseLeave={e => (e.currentTarget.style.color = 'rgba(242,236,224,0.7)')}
                  >
                    Sign in
                    <ArrowRight size={12} style={{ opacity: 0.3 }} />
                  </motion.a>
                )}
              </nav>

              {/* Drawer CTA — hidden when already signed in */}
              {!isAuthed && (
                <div style={{ padding: '28px 36px', borderTop: '0.5px solid rgba(242,236,224,0.08)' }}>
                  <motion.div
                    initial={{ opacity: 0, y: 10 }}
                    animate={{ opacity: 1, y: 0 }}
                    transition={{ delay: 0.4, duration: 0.35 }}
                  >
                    <div style={{
                      width: '20px',
                      height: '2px',
                      background: 'var(--red)',
                      marginBottom: '14px',
                    }} />
                    <p className="font-serif" style={{
                      fontSize: '16px',
                      fontStyle: 'italic',
                      fontWeight: 700,
                      color: 'var(--paper)',
                      lineHeight: 1.4,
                      marginBottom: '16px',
                      opacity: 0.8,
                    }}>
                      Run your first simulation free.
                    </p>
                    <Link
                      href="/signup"
                      onClick={() => setMenuOpen(false)}
                      style={{
                        display: 'flex',
                        alignItems: 'center',
                        justifyContent: 'center',
                        gap: '8px',
                        background: 'var(--red)',
                        color: '#fff',
                        padding: '12px 20px',
                        fontSize: '11px',
                        letterSpacing: '0.1em',
                        textTransform: 'uppercase',
                        fontWeight: 500,
                        textDecoration: 'none',
                      }}
                    >
                      Get started <ArrowRight size={12} />
                    </Link>
                  </motion.div>
                </div>
              )}

              {/* Footer strip */}
              <div style={{ padding: '16px 36px', borderTop: '0.5px solid rgba(242,236,224,0.06)' }}>
                <p style={{ fontSize: '10px', color: 'rgba(242,236,224,0.2)', letterSpacing: '0.1em' }}>
                  © 2026 TheCee. Simulate before you build.
                </p>
              </div>
          </motion.div>
        )}
      </AnimatePresence>

      {/* ━━━ HERO ━━━ */}
      <section ref={heroRef} style={{ borderBottom: '0.5px solid var(--border-color)', overflow: 'hidden' }}>
        <motion.div style={{ opacity: heroOpacity, y: heroY }}>

          {/* Three-column hero grid */}
          <div style={{
            display: 'grid',
            gridTemplateColumns: '1fr 2.2fr 1fr',
            minHeight: '75vh',
          }}>

            {/* Left column — features list */}
            <div style={{
              borderRight: '0.5px solid var(--border-color)',
              padding: '40px 32px',
              display: 'flex',
              flexDirection: 'column',
              justifyContent: 'space-between',
            }}>
              <div>
                <div style={{
                  fontSize: '9px',
                  letterSpacing: '0.2em',
                  textTransform: 'uppercase',
                  color: 'var(--ink-secondary)',
                  marginBottom: '16px',
                }}>
                  Features
                </div>
                {['Idea validation', 'Risk discovery', 'Revenue forecasting', 'Launch readiness', 'Pricing confidence'].map(item => (
                  <div
                    key={item}
                    style={{
                      display: 'flex',
                      alignItems: 'center',
                      gap: '8px',
                      padding: '9px 0',
                      borderBottom: '0.5px solid var(--border-color)',
                      fontSize: '11px',
                      color: 'var(--ink-secondary)',
                    }}
                  >
                    <Minus size={8} color="var(--red)" />
                    {item}
                  </div>
                ))}
              </div>

              <div>
                <div style={{ width: '24px', height: '2px', background: 'var(--red)', marginBottom: '10px' }} />
                <p style={{ fontSize: '11px', color: 'var(--ink-secondary)', lineHeight: 1.7 }}>
                  TheCee simulates reality before you commit to it.
                </p>
              </div>
            </div>

            {/* Centre column — main story */}
            <div style={{
              borderRight: '0.5px solid var(--border-color)',
              padding: '48px 56px',
              display: 'flex',
              flexDirection: 'column',
              justifyContent: 'space-between',
            }}>
              <div>
                <SectionKicker label="Cover story" />

                <motion.h1
                  initial={{ opacity: 0, y: 24 }}
                  animate={{ opacity: 1, y: 0 }}
                  transition={{ duration: 0.9, delay: 0.2 }}
                  className="font-serif"
                  style={{
                    fontSize: 'clamp(44px, 5.5vw, 80px)',
                    fontWeight: 900,
                    lineHeight: 1.02,
                    letterSpacing: '-0.02em',
                    color: 'var(--ink)',
                    marginBottom: '28px',
                  }}
                >
                  Will your{' '}
                  <WordRotator />
                  <br />
                  <span style={{ color: 'var(--ink-tertiary)', fontStyle: 'italic' }}>actually work?</span>
                </motion.h1>

                <div style={{ height: '0.5px', background: 'var(--border-color)', marginBottom: '28px' }} />

                <motion.p
                  initial={{ opacity: 0 }}
                  animate={{ opacity: 1 }}
                  transition={{ duration: 0.7, delay: 0.5 }}
                  style={{
                    fontSize: '16px',
                    color: 'var(--ink-secondary)',
                    lineHeight: 1.8,
                    maxWidth: '480px',
                    marginBottom: '36px',
                    fontWeight: 300,
                  }}
                >
                  TheCee stress-tests your idea against thousands of real-world
                  scenarios before you commit — giving you clarity that no amount
                  of planning, advice, or gut feeling ever can.
                </motion.p>

                <motion.div
                  initial={{ opacity: 0, y: 12 }}
                  animate={{ opacity: 1, y: 0 }}
                  transition={{ duration: 0.6, delay: 0.7 }}
                  style={{ display: 'flex', alignItems: 'center', gap: '20px', flexWrap: 'wrap' }}
                >
                  <Link
                    href="/signup"
                    style={{
                      background: 'var(--ink)',
                      color: 'var(--paper)',
                      padding: '12px 28px',
                      fontSize: '11px',
                      letterSpacing: '0.1em',
                      textTransform: 'uppercase',
                      fontWeight: 500,
                      textDecoration: 'none',
                      display: 'inline-flex',
                      alignItems: 'center',
                      gap: '8px',
                      transition: 'background 0.2s',
                    }}
                    onMouseEnter={e => (e.currentTarget.style.background = 'var(--red)')}
                    onMouseLeave={e => (e.currentTarget.style.background = 'var(--ink)')}
                  >
                    Validate your idea <ArrowRight size={12} />
                  </Link>
                  <a
                    href="#how"
                    style={{
                      fontSize: '11px',
                      color: 'var(--ink-secondary)',
                      letterSpacing: '0.08em',
                      textTransform: 'uppercase',
                      textDecoration: 'none',
                      borderBottom: '0.5px solid var(--border-color)',
                      paddingBottom: '2px',
                      transition: 'color 0.2s',
                    }}
                    onMouseEnter={e => (e.currentTarget.style.color = 'var(--ink)')}
                    onMouseLeave={e => (e.currentTarget.style.color = 'var(--ink-secondary)')}
                  >
                    Read how it works →
                  </a>
                </motion.div>
              </div>

              {/* Pull quote */}
              <div style={{
                borderTop: '0.5px solid var(--border-color)',
                paddingTop: '28px',
                display: 'flex',
                alignItems: 'center',
                gap: '32px',
              }}>
                <div style={{ flex: 1 }}>
                  <p
                    className="font-serif"
                    style={{
                      fontSize: '15px',
                      fontStyle: 'italic',
                      fontWeight: 700,
                      color: 'var(--ink)',
                      lineHeight: 1.5,
                    }}
                  >
                    &ldquo;Know before you build. Not after you have spent six months on something that will not work.&rdquo;
                  </p>
                </div>
                <div style={{ display: 'flex', gap: '24px', flexShrink: 0 }}>
                  {[{ v: '240+', l: 'Founders' }, { v: '10K+', l: 'Scenarios' }].map(({ v, l }) => (
                    <div key={l} style={{ textAlign: 'center' }}>
                      <div className="font-serif" style={{ fontSize: '26px', fontWeight: 900, color: 'var(--ink)', lineHeight: 1 }}>{v}</div>
                      <div style={{ fontSize: '9px', color: 'var(--ink-tertiary)', letterSpacing: '0.12em', textTransform: 'uppercase', marginTop: '4px' }}>{l}</div>
                    </div>
                  ))}
                </div>
              </div>
            </div>

            {/* Right column — who + CTA box */}
            <div style={{
              padding: '40px 32px',
              display: 'flex',
              flexDirection: 'column',
              justifyContent: 'space-between',
            }}>
              <div>
                <div style={{ fontSize: '9px', letterSpacing: '0.2em', textTransform: 'uppercase', color: 'var(--ink-secondary)', marginBottom: '16px' }}>
                  Who it&apos;s for
                </div>
                {['First-time founders', 'Product managers', 'D2C brands', 'Side project builders'].map(item => (
                  <div
                    key={item}
                    style={{
                      padding: '10px 0',
                      borderBottom: '0.5px solid var(--border-color)',
                      display: 'flex',
                      justifyContent: 'space-between',
                      alignItems: 'center',
                      fontSize: '12px',
                      color: 'var(--ink)',
                      cursor: 'pointer',
                      transition: 'color 0.2s',
                    }}
                    onMouseEnter={e => (e.currentTarget.style.color = 'var(--red)')}
                    onMouseLeave={e => (e.currentTarget.style.color = 'var(--ink)')}
                  >
                    {item} <ArrowUpRight size={11} />
                  </div>
                ))}
              </div>

              {/* Bordered CTA box */}
              <div style={{
                border: '1.5px solid var(--ink)',
                padding: '20px',
                background: 'var(--paper-dark)',
              }}>
                <div style={{ fontSize: '9px', letterSpacing: '0.2em', textTransform: 'uppercase', color: 'var(--red)', marginBottom: '10px', fontWeight: 500 }}>
                  Free to start
                </div>
                <p
                  className="font-serif"
                  style={{ fontSize: '15px', fontWeight: 800, color: 'var(--ink)', lineHeight: 1.3, marginBottom: '14px', fontStyle: 'italic' }}
                >
                  Run your first simulation at no cost.
                </p>
                <Link
                  href="/signup"
                  style={{
                    display: 'block',
                    textAlign: 'center',
                    background: 'var(--red)',
                    color: '#fff',
                    padding: '8px',
                    fontSize: '10px',
                    letterSpacing: '0.1em',
                    textTransform: 'uppercase',
                    fontWeight: 500,
                    textDecoration: 'none',
                    transition: 'opacity 0.2s',
                  }}
                  onMouseEnter={e => (e.currentTarget.style.opacity = '0.85')}
                  onMouseLeave={e => (e.currentTarget.style.opacity = '1')}
                >
                  Start now →
                </Link>
              </div>
            </div>

          </div>
        </motion.div>
      </section>

      <SimulationTimeline />

      {/* ━━━ HOW IT WORKS ━━━ */}
      <section id="how" style={{ borderBottom: '0.5px solid var(--border-color)' }}>
        <div style={{ maxWidth: '1200px', margin: '0 auto', padding: '80px 48px' }}>

          <Reveal>
            <SectionKicker label="Process" />
            <h2
              className="font-serif"
              style={{
                fontSize: 'clamp(36px, 4vw, 60px)',
                fontWeight: 900,
                fontStyle: 'italic',
                color: 'var(--ink)',
                lineHeight: 1.05,
                letterSpacing: '-0.02em',
                marginBottom: '64px',
              }}
            >
              Three steps to certainty.
            </h2>
          </Reveal>

          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)' }}>
            {STEPS.map(({ n, title, body, kicker }, i) => (
              <Reveal key={n} delay={i * 0.1}>
                <div style={{
                  paddingTop: '40px',
                  paddingBottom: '40px',
                  paddingLeft: i > 0 ? '40px' : '0',
                  paddingRight: i < 2 ? '40px' : '0',
                  borderRight: i < 2 ? '0.5px solid var(--border-color)' : 'none',
                  minHeight: '260px',
                  display: 'flex',
                  flexDirection: 'column',
                  justifyContent: 'space-between',
                }}>
                  <div>
                    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: '20px' }}>
                      <span style={{ fontSize: '9px', color: 'var(--red)', letterSpacing: '0.2em', textTransform: 'uppercase', fontWeight: 500 }}>
                        {kicker}
                      </span>
                      <span className="font-serif" style={{ fontSize: '48px', fontWeight: 900, color: 'var(--paper-dark)', lineHeight: 1, letterSpacing: '-0.03em' }}>
                        {n}
                      </span>
                    </div>
                    <div style={{ height: '2px', background: 'var(--ink)', width: '24px', marginBottom: '20px' }} />
                    <h3
                      className="font-serif"
                      style={{
                        fontSize: '22px',
                        fontWeight: 800,
                        color: 'var(--ink)',
                        lineHeight: 1.2,
                        letterSpacing: '-0.01em',
                        marginBottom: '12px',
                        fontStyle: 'italic',
                      }}
                    >
                      {title}
                    </h3>
                    <p style={{ fontSize: '13px', color: 'var(--ink-secondary)', lineHeight: 1.8 }}>{body}</p>
                  </div>
                </div>
              </Reveal>
            ))}
          </div>

        </div>
      </section>

      {/* ━━━ WHO IT'S FOR ━━━ */}
      <section id="who" style={{ borderBottom: '0.5px solid var(--border-color)', background: 'var(--paper-dark)' }}>
        <div style={{ maxWidth: '1200px', margin: '0 auto', padding: '80px 48px' }}>

          <Reveal>
            <SectionKicker label="Who it's for" />
            <h2
              className="font-serif"
              style={{
                fontSize: 'clamp(32px, 3.5vw, 52px)',
                fontWeight: 900,
                fontStyle: 'italic',
                color: 'var(--ink)',
                lineHeight: 1.05,
                letterSpacing: '-0.02em',
                marginBottom: '64px',
                maxWidth: '640px',
              }}
            >
              Built for people who cannot afford to guess.
            </h2>
          </Reveal>

          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(2, 1fr)' }}>
            {WHO.map(({ title, body, tag }, i) => (
              <Reveal key={title} delay={i * 0.08}>
                <div
                  style={{
                    padding: '36px',
                    borderTop: '0.5px solid var(--border-color)',
                    borderRight: i % 2 === 0 ? '0.5px solid var(--border-color)' : 'none',
                    background: 'var(--paper-dark)',
                    transition: 'background 0.3s',
                    cursor: 'default',
                  }}
                  onMouseEnter={e => (e.currentTarget.style.background = 'var(--paper)')}
                  onMouseLeave={e => (e.currentTarget.style.background = 'var(--paper-dark)')}
                >
                  <div style={{
                    display: 'inline-block',
                    fontSize: '9px',
                    color: 'var(--red)',
                    letterSpacing: '0.18em',
                    textTransform: 'uppercase',
                    fontWeight: 500,
                    borderLeft: '2px solid var(--red)',
                    paddingLeft: '8px',
                    marginBottom: '20px',
                  }}>
                    {tag}
                  </div>
                  <h3
                    className="font-serif"
                    style={{
                      fontSize: '22px',
                      fontWeight: 800,
                      color: 'var(--ink)',
                      lineHeight: 1.2,
                      fontStyle: 'italic',
                      marginBottom: '12px',
                    }}
                  >
                    {title}
                  </h3>
                  <p style={{ fontSize: '13px', color: 'var(--ink-secondary)', lineHeight: 1.8 }}>{body}</p>
                </div>
              </Reveal>
            ))}
          </div>

        </div>
      </section>

      {/* ━━━ STATS ━━━ */}
      <section style={{ borderBottom: '0.5px solid var(--border-color)' }}>
        <div style={{ maxWidth: '1200px', margin: '0 auto', padding: '64px 48px' }}>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)' }}>
            {STATS.map(({ value, label }, i) => (
              <Reveal key={label} delay={i * 0.07}>
                <div style={{
                  padding: '32px 40px',
                  borderRight: i < 3 ? '0.5px solid var(--border-color)' : 'none',
                  textAlign: 'center',
                }}>
                  <div
                    className="font-serif"
                    style={{
                      fontSize: 'clamp(28px, 3vw, 44px)',
                      fontWeight: 900,
                      color: 'var(--ink)',
                      lineHeight: 1,
                      letterSpacing: '-0.02em',
                      marginBottom: '8px',
                    }}
                  >
                    {value}
                  </div>
                  <div style={{
                    fontSize: '10px',
                    color: 'var(--ink-tertiary)',
                    letterSpacing: '0.12em',
                    textTransform: 'uppercase',
                    lineHeight: 1.5,
                  }}>
                    {label}
                  </div>
                </div>
              </Reveal>
            ))}
          </div>
        </div>
      </section>

      {/* ━━━ FINAL CTA ━━━ */}
      <section id="pricing" style={{ background: 'var(--ink)', borderBottom: '3px solid var(--ink)' }}>
        <div style={{
          maxWidth: '1200px',
          margin: '0 auto',
          padding: '100px 48px',
          display: 'grid',
          gridTemplateColumns: '1.5fr 1fr',
          gap: '80px',
          alignItems: 'center',
        }}>
          <Reveal>
            <div style={{ height: '2px', width: '24px', background: 'var(--red)', marginBottom: '24px' }} />
            <h2
              className="font-serif"
              style={{
                fontSize: 'clamp(36px, 4vw, 64px)',
                fontWeight: 900,
                fontStyle: 'italic',
                color: 'var(--paper)',
                lineHeight: 1.05,
                letterSpacing: '-0.02em',
                marginBottom: '24px',
              }}
            >
              Your next decision<br />
              <span style={{ color: 'rgba(242,236,224,0.3)' }}>deserves certainty.</span>
            </h2>
            <p style={{ fontSize: '14px', color: 'rgba(242,236,224,0.5)', lineHeight: 1.8, marginBottom: '36px', maxWidth: '380px' }}>
              Stop planning. Stop guessing. Start simulating — and know before you build.
            </p>
            <Link
              href="/signup"
              style={{
                display: 'inline-flex',
                alignItems: 'center',
                gap: '10px',
                background: 'var(--red)',
                color: '#fff',
                padding: '14px 32px',
                fontSize: '11px',
                letterSpacing: '0.1em',
                textTransform: 'uppercase',
                fontWeight: 500,
                textDecoration: 'none',
                transition: 'opacity 0.2s',
              }}
              onMouseEnter={e => (e.currentTarget.style.opacity = '0.85')}
              onMouseLeave={e => (e.currentTarget.style.opacity = '1')}
            >
              Validate your idea free <ArrowRight size={13} />
            </Link>
          </Reveal>

          <Reveal delay={0.15}>
            <div style={{ borderLeft: '0.5px solid rgba(242,236,224,0.1)', paddingLeft: '60px' }}>
              <div style={{ height: '2px', width: '20px', background: 'var(--red)', marginBottom: '16px' }} />
              <p
                className="font-serif"
                style={{
                  fontSize: '20px',
                  fontStyle: 'italic',
                  fontWeight: 700,
                  color: 'var(--paper)',
                  lineHeight: 1.5,
                  marginBottom: '20px',
                  opacity: 0.9,
                }}
              >
                &ldquo;Every decision made without simulation is a decision made blind.&rdquo;
              </p>
              <p style={{ fontSize: '10px', color: 'rgba(242,236,224,0.4)', letterSpacing: '0.15em', textTransform: 'uppercase' }}>
                — TheCee, 2026
              </p>
            </div>
          </Reveal>
        </div>
      </section>

      {/* ━━━ FOOTER ━━━ */}
      <footer style={{ background: 'var(--ink)', borderTop: '0.5px solid rgba(242,236,224,0.08)' }}>
        <div style={{
          maxWidth: '1200px',
          margin: '0 auto',
          padding: '24px 48px',
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'center',
        }}>
          <span
            className="font-serif"
            style={{ fontSize: '18px', fontWeight: 900, fontStyle: 'italic', color: 'var(--paper)', opacity: 0.4, letterSpacing: '-0.02em' }}
          >
            TheCee
          </span>
          <p style={{ fontSize: '10px', color: 'rgba(242,236,224,0.25)', letterSpacing: '0.1em' }}>
            © 2026 TheCee. Simulate before you build.
          </p>
          <div style={{ display: 'flex', gap: '24px' }}>
            {['Privacy', 'Terms', 'Contact'].map(item => (
              <a
                key={item}
                href="#"
                style={{
                  fontSize: '10px',
                  color: 'rgba(242,236,224,0.3)',
                  letterSpacing: '0.12em',
                  textTransform: 'uppercase',
                  textDecoration: 'none',
                  transition: 'color 0.2s',
                }}
                onMouseEnter={e => (e.currentTarget.style.color = 'rgba(242,236,224,0.7)')}
                onMouseLeave={e => (e.currentTarget.style.color = 'rgba(242,236,224,0.3)')}
              >
                {item}
              </a>
            ))}
          </div>
        </div>
      </footer>

    </div>
  )
}
