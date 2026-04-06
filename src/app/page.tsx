'use client'

import { useRef, useState, useEffect } from 'react'
import { motion, useScroll, useTransform, AnimatePresence } from 'framer-motion'
import Link from 'next/link'
import { ArrowRight, ArrowUpRight, Minus } from 'lucide-react'

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

const MARQUEE_ITEMS = [
  'Idea Validation', 'Launch Readiness', 'Product-Market Fit',
  'Customer Behaviour', 'Risk Discovery', 'Revenue Forecasting',
  'Growth Scenarios', 'Startup Stress Testing', 'Pricing Confidence',
  'Decision Intelligence',
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

  return (
    <div style={{ background: 'var(--paper)', minHeight: '100vh' }}>

      {/* ━━━ HEADER / NAVBAR ━━━ */}
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
        {/* Main nav row */}
        <div style={{
          padding: '16px 48px',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
        }}>
          {/* Left nav links */}
          <div style={{ display: 'flex', gap: '32px', alignItems: 'center' }}>
            {['How it works', 'Use cases', 'Pricing'].map(item => (
              <a
                key={item}
                href="#"
                style={{
                  fontSize: '11px',
                  color: 'var(--ink-secondary)',
                  letterSpacing: '0.08em',
                  textTransform: 'uppercase',
                  textDecoration: 'none',
                  transition: 'color 0.2s',
                }}
                onMouseEnter={e => (e.currentTarget.style.color = 'var(--ink)')}
                onMouseLeave={e => (e.currentTarget.style.color = 'var(--ink-secondary)')}
              >
                {item}
              </a>
            ))}
          </div>

          {/* Masthead */}
          <div style={{ textAlign: 'center' }}>
            <div
              className="font-serif"
              style={{
                fontSize: '36px',
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

          {/* Right auth links */}
          <div style={{ display: 'flex', gap: '20px', alignItems: 'center' }}>
            <Link
              href="/login"
              style={{
                fontSize: '11px',
                color: 'var(--ink-secondary)',
                letterSpacing: '0.08em',
                textTransform: 'uppercase',
                textDecoration: 'none',
                transition: 'color 0.2s',
              }}
              onMouseEnter={e => (e.currentTarget.style.color = 'var(--ink)')}
              onMouseLeave={e => (e.currentTarget.style.color = 'var(--ink-secondary)')}
            >
              Sign in
            </Link>
            <Link
              href="/signup"
              style={{
                fontSize: '11px',
                color: 'var(--paper)',
                background: 'var(--ink)',
                padding: '8px 18px',
                letterSpacing: '0.08em',
                textTransform: 'uppercase',
                textDecoration: 'none',
                fontWeight: 500,
                display: 'inline-flex',
                alignItems: 'center',
                gap: '6px',
                transition: 'background 0.2s',
              }}
              onMouseEnter={e => (e.currentTarget.style.background = 'var(--red)')}
              onMouseLeave={e => (e.currentTarget.style.background = 'var(--ink)')}
            >
              Get started <ArrowRight size={11} />
            </Link>
          </div>
        </div>
      </motion.header>

      {/* ━━━ HERO ━━━ */}
      <section ref={heroRef} style={{ borderBottom: '0.5px solid var(--border-color)', overflow: 'hidden' }}>
        <motion.div style={{ opacity: heroOpacity, y: heroY }}>

          {/* Issue line */}
          <div style={{
            padding: '10px 48px',
            borderBottom: '0.5px solid var(--border-color)',
            display: 'flex',
            justifyContent: 'space-between',
            alignItems: 'center',
            background: 'var(--paper-dark)',
          }}>
            <span style={{ fontSize: '10px', color: 'var(--ink-secondary)', letterSpacing: '0.15em', textTransform: 'uppercase' }}>
              Vol. 01 — Issue 01
            </span>
            <span style={{ fontSize: '10px', color: 'var(--red)', letterSpacing: '0.15em', textTransform: 'uppercase', fontWeight: 500 }}>
              ◆ Now in early access
            </span>
            <span style={{ fontSize: '10px', color: 'var(--ink-secondary)', letterSpacing: '0.12em' }}>
              April 2026
            </span>
          </div>

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

      {/* ━━━ MARQUEE ━━━ */}
      <div style={{
        overflow: 'hidden',
        background: 'var(--ink)',
        padding: '10px 0',
        borderBottom: '0.5px solid rgba(242,236,224,0.08)',
      }}>
        <div className="animate-marquee" style={{ display: 'flex', whiteSpace: 'nowrap' }}>
          {[...Array(2)].map((_, i) => (
            <div key={i} style={{ display: 'flex', alignItems: 'center' }}>
              {MARQUEE_ITEMS.map((item, j) => (
                <span key={`${i}-${j}`} style={{ display: 'flex', alignItems: 'center', gap: '24px', padding: '0 24px' }}>
                  <span style={{ fontSize: '10px', letterSpacing: '0.2em', textTransform: 'uppercase', color: 'rgba(242,236,224,0.5)' }}>
                    {item}
                  </span>
                  <span style={{ width: '3px', height: '3px', borderRadius: '50%', background: 'var(--red)', display: 'inline-block', flexShrink: 0 }} />
                </span>
              ))}
            </div>
          ))}
        </div>
      </div>

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
      <section style={{ borderBottom: '0.5px solid var(--border-color)', background: 'var(--paper-dark)' }}>
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
      <section style={{ background: 'var(--ink)', borderBottom: '3px solid var(--ink)' }}>
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
