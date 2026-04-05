'use client'

import { useRef, useEffect, useState } from 'react'
import {
  motion,
  useScroll,
  useTransform,
  useSpring,
  AnimatePresence,
} from 'framer-motion'
import Link from 'next/link'
import { ArrowRight, ArrowUpRight } from 'lucide-react'

/* ─── CONSTANTS ─────────────────────────────────── */
const NAV_LINKS = ['How it works', 'Use cases', 'Pricing']

const WORDS = ['startup', 'product', 'idea', 'launch', 'decision']

const STEPS = [
  {
    n: '01',
    title: 'Describe your idea',
    body: 'Write your product or business concept in plain language. No forms, no templates. Just your idea as you see it.',
  },
  {
    n: '02',
    title: 'We stress-test it',
    body: 'TheCee runs your idea through thousands of real-world scenarios — different customers, market conditions, risks you have not considered.',
  },
  {
    n: '03',
    title: 'You get clarity',
    body: 'See what will work, what will fail, and the precise changes that shift the odds in your favour — before you spend a rupee.',
  },
]

const WHO = [
  { label: 'First-time founders', sub: 'Validate before you build' },
  { label: 'Product managers', sub: 'Data over opinion' },
  { label: 'D2C brands', sub: 'Test before you manufacture' },
  { label: 'Side project builders', sub: 'Know before you commit' },
]

const STATS = [
  { value: '10,000+', label: 'Scenarios per test' },
  { value: '< 2 min', label: 'Time to first insight' },
  { value: '3×', label: 'Cross-validated by default' },
  { value: '240+', label: 'Founders validated' },
]

/* ─── WORD ROTATOR ───────────────────────────────── */
function WordRotator() {
  const [index, setIndex] = useState(0)
  useEffect(() => {
    const t = setInterval(() => setIndex(i => (i + 1) % WORDS.length), 2200)
    return () => clearInterval(t)
  }, [])
  return (
    <span
      className="relative inline-block overflow-hidden"
      style={{ minWidth: '260px', display: 'inline-flex', justifyContent: 'center' }}
    >
      <AnimatePresence mode="wait">
        <motion.span
          key={WORDS[index]}
          initial={{ y: 60, opacity: 0, filter: 'blur(8px)' }}
          animate={{ y: 0, opacity: 1, filter: 'blur(0px)' }}
          exit={{ y: -60, opacity: 0, filter: 'blur(8px)' }}
          transition={{ duration: 0.55, ease: [0.76, 0, 0.24, 1] }}
          style={{
            background: 'linear-gradient(135deg, #7B6EF6 0%, #a78bfa 50%, #38bdf8 100%)',
            WebkitBackgroundClip: 'text',
            WebkitTextFillColor: 'transparent',
            backgroundClip: 'text',
            display: 'inline-block',
          }}
        >
          {WORDS[index]}
        </motion.span>
      </AnimatePresence>
    </span>
  )
}

/* ─── CINEMATIC LINE ─────────────────────────────── */
function CinematicRule() {
  return (
    <div
      className="relative w-full h-px overflow-hidden"
      style={{ background: 'rgba(255,255,255,0.05)' }}
    >
      <div className="beam" />
    </div>
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
      initial={{ opacity: 0, y: 40 }}
      whileInView={{ opacity: 1, y: 0 }}
      viewport={{ once: true, margin: '-80px' }}
      transition={{ duration: 0.9, delay, ease: [0.25, 0.46, 0.45, 0.94] }}
      className={className}
    >
      {children}
    </motion.div>
  )
}

/* ─── MAIN PAGE ──────────────────────────────────── */
export default function LandingPage() {
  const containerRef = useRef<HTMLDivElement>(null)
  const heroRef = useRef<HTMLDivElement>(null)

  const { scrollYProgress } = useScroll({
    target: heroRef,
    offset: ['start start', 'end start'],
  })

  const heroOpacity = useTransform(scrollYProgress, [0, 0.7], [1, 0])
  const heroScale = useTransform(scrollYProgress, [0, 1], [1, 0.94])
  const heroY = useTransform(scrollYProgress, [0, 1], [0, 50])
  const smoothY = useSpring(heroY, { stiffness: 80, damping: 20 })
  const imgScale = useTransform(scrollYProgress, [0, 1], [1.05, 1.0])

  return (
    <div ref={containerRef} className="relative" style={{ background: 'var(--bg)' }}>

      {/* ━━━ NAVBAR ━━━ */}
      <motion.nav
        initial={{ opacity: 0 }}
        animate={{ opacity: 1 }}
        transition={{ duration: 1, delay: 0.2 }}
        className="fixed top-0 left-0 right-0 z-50 flex items-center justify-between px-8 py-6"
        style={{ background: 'transparent' }}
      >
        <div className="flex items-center gap-3">
          <svg width="20" height="20" viewBox="0 0 20 20" fill="none">
            <circle cx="10" cy="10" r="3" fill="#7B6EF6" />
            <circle cx="10" cy="10" r="7" stroke="#7B6EF6" strokeWidth="0.75" opacity="0.35" />
            <circle cx="10" cy="10" r="10" stroke="#7B6EF6" strokeWidth="0.5" opacity="0.12" />
          </svg>
          <span className="font-display font-700 tracking-tight" style={{ fontSize: '15px', color: '#f0f0f5' }}>
            TheCee
          </span>
        </div>

        <div className="hidden md:flex items-center gap-10">
          {NAV_LINKS.map(link => (
            <a
              key={link}
              href="#"
              className="transition-colors duration-300"
              style={{
                fontSize: '11px',
                letterSpacing: '0.12em',
                textTransform: 'uppercase',
                color: 'var(--text-secondary)',
                fontWeight: 400,
              }}
              onMouseEnter={e => (e.currentTarget.style.color = '#f0f0f5')}
              onMouseLeave={e => (e.currentTarget.style.color = 'var(--text-secondary)')}
            >
              {link}
            </a>
          ))}
        </div>

        <div className="flex items-center gap-6">
          <Link
            href="/login"
            className="transition-colors duration-300"
            style={{
              fontSize: '11px',
              letterSpacing: '0.1em',
              textTransform: 'uppercase',
              color: 'var(--text-secondary)',
            }}
          >
            Sign in
          </Link>
          <Link
            href="/signup"
            className="relative flex items-center gap-2 px-5 py-2.5 overflow-hidden"
            style={{
              fontSize: '11px',
              fontWeight: 500,
              letterSpacing: '0.1em',
              textTransform: 'uppercase',
              border: '1px solid rgba(123,110,246,0.5)',
              color: '#f0f0f5',
              background: 'rgba(123,110,246,0.08)',
            }}
          >
            Get started <ArrowRight className="w-3 h-3" />
          </Link>
        </div>
      </motion.nav>

      {/* ━━━ HERO ━━━ */}
      <section
        ref={heroRef}
        className="relative h-screen flex flex-col items-center justify-center overflow-hidden"
      >
        {/* Background image with parallax */}
        <motion.div style={{ scale: imgScale }} className="absolute inset-0 z-0">
          <img
            src="/nature-bg.jpeg"
            alt=""
            className="w-full h-full object-cover object-center"
            style={{ opacity: 0.28 }}
          />
          {/* Cinematic letterbox gradient */}
          <div
            className="absolute inset-0"
            style={{
              background: `
                linear-gradient(to bottom,
                  rgba(5,5,7,0.85) 0%,
                  rgba(5,5,7,0.2) 25%,
                  rgba(5,5,7,0.15) 50%,
                  rgba(5,5,7,0.5) 75%,
                  rgba(5,5,7,1) 100%
                )
              `,
            }}
          />
          {/* Side vignette */}
          <div
            className="absolute inset-0"
            style={{
              background:
                'radial-gradient(ellipse at center, transparent 40%, rgba(5,5,7,0.8) 100%)',
            }}
          />
        </motion.div>

        {/* Accent spotlight */}
        <div
          className="spotlight w-96 h-96 opacity-10"
          style={{ background: '#7B6EF6', top: '20%', left: '50%', transform: 'translate(-50%,-50%)' }}
        />

        {/* Hero content */}
        <motion.div
          style={{ opacity: heroOpacity, y: smoothY, scale: heroScale }}
          className="relative z-10 text-center px-6 max-w-5xl mx-auto"
        >
          {/* Pre-label */}
          <motion.div
            initial={{ opacity: 0, y: 16 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.8, delay: 0.4 }}
            className="flex items-center justify-center gap-3 mb-10"
          >
            <div style={{ width: '40px', height: '1px', background: 'rgba(123,110,246,0.6)' }} />
            <span
              style={{
                fontSize: '10px',
                letterSpacing: '0.25em',
                textTransform: 'uppercase',
                color: '#7B6EF6',
                fontWeight: 400,
              }}
            >
              Simulation intelligence
            </span>
            <div style={{ width: '40px', height: '1px', background: 'rgba(123,110,246,0.6)' }} />
          </motion.div>

          {/* Main headline */}
          <motion.h1
            initial={{ opacity: 0, y: 32 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 1, delay: 0.55, ease: [0.25, 0.46, 0.45, 0.94] }}
            className="cinematic-text mb-6"
            style={{ fontSize: 'clamp(52px, 8vw, 108px)', color: 'var(--text-primary)' }}
          >
            Will your{' '}
            <WordRotator />
            <br />
            <span style={{ color: 'rgba(240,240,245,0.35)' }}>actually work?</span>
          </motion.h1>

          {/* Subheadline */}
          <motion.p
            initial={{ opacity: 0, y: 20 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.8, delay: 0.8 }}
            style={{
              fontSize: '16px',
              color: 'var(--text-secondary)',
              lineHeight: 1.8,
              maxWidth: '520px',
              margin: '0 auto 48px',
              fontWeight: 300,
            }}
          >
            TheCee stress-tests your idea against thousands of real scenarios before
            you commit — giving you clarity no amount of planning can.
          </motion.p>

          {/* CTAs */}
          <motion.div
            initial={{ opacity: 0, y: 16 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.7, delay: 1 }}
            className="flex flex-col sm:flex-row items-center justify-center gap-4"
          >
            <Link
              href="/signup"
              className="group relative flex items-center gap-3 px-8 py-4 overflow-hidden"
              style={{
                background: '#7B6EF6',
                color: '#fff',
                fontSize: '13px',
                fontWeight: 500,
                letterSpacing: '0.06em',
                textTransform: 'uppercase',
              }}
            >
              <span className="relative z-10 flex items-center gap-2">
                Validate your idea
                <ArrowRight className="w-4 h-4 group-hover:translate-x-1 transition-transform duration-300" />
              </span>
              <motion.div
                className="absolute inset-0"
                style={{ background: 'rgba(255,255,255,0.1)' }}
                initial={{ x: '-100%' }}
                whileHover={{ x: '100%' }}
                transition={{ duration: 0.4 }}
              />
            </Link>

            <a
              href="#how"
              className="flex items-center gap-2 px-6 py-4 transition-colors duration-300"
              style={{
                fontSize: '12px',
                color: 'var(--text-secondary)',
                letterSpacing: '0.1em',
                textTransform: 'uppercase',
              }}
              onMouseEnter={e => (e.currentTarget.style.color = '#f0f0f5')}
              onMouseLeave={e => (e.currentTarget.style.color = 'var(--text-secondary)')}
            >
              Watch how it works
            </a>
          </motion.div>
        </motion.div>

        {/* Scroll indicator */}
        <motion.div
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          transition={{ delay: 1.6, duration: 1 }}
          className="absolute bottom-10 left-1/2 -translate-x-1/2 z-10 flex flex-col items-center gap-2"
        >
          <div
            style={{
              fontSize: '9px',
              letterSpacing: '0.2em',
              textTransform: 'uppercase',
              color: 'var(--text-secondary)',
            }}
          >
            Scroll
          </div>
          <motion.div
            animate={{ y: [0, 8, 0] }}
            transition={{ duration: 1.8, repeat: Infinity, ease: 'easeInOut' }}
            style={{
              width: '1px',
              height: '40px',
              background: 'linear-gradient(to bottom, rgba(123,110,246,0.8), transparent)',
            }}
          />
        </motion.div>
      </section>

      {/* ━━━ BELOW HERO — SOLID DARK ━━━ */}
      <div style={{ background: 'var(--bg)', position: 'relative', zIndex: 10 }}>

        {/* ━━━ MARQUEE ━━━ */}
        <div
          className="relative overflow-hidden py-5"
          style={{ borderTop: '1px solid var(--border-color)', borderBottom: '1px solid var(--border-color)' }}
        >
          <CinematicRule />
          <div className="flex animate-marquee whitespace-nowrap py-4">
            {[...Array(2)].map((_, i) => (
              <div key={i} className="flex items-center">
                {[
                  'Idea Validation',
                  'Launch Readiness',
                  'Product-Market Fit',
                  'Customer Behaviour',
                  'Risk Discovery',
                  'Revenue Forecasting',
                  'Growth Scenarios',
                  'Startup Stress Testing',
                  'Pricing Confidence',
                  'Decision Intelligence',
                ].map((item, j) => (
                  <span key={`${i}-${j}`} className="flex items-center gap-8 px-8">
                    <span
                      style={{
                        fontSize: '10px',
                        letterSpacing: '0.2em',
                        textTransform: 'uppercase',
                        color: 'var(--text-secondary)',
                      }}
                    >
                      {item}
                    </span>
                    <span
                      style={{
                        width: '3px',
                        height: '3px',
                        borderRadius: '50%',
                        background: 'rgba(123,110,246,0.4)',
                        display: 'inline-block',
                      }}
                    />
                  </span>
                ))}
              </div>
            ))}
          </div>
        </div>

        {/* ━━━ HOW IT WORKS ━━━ */}
        <section id="how" className="relative px-8 py-40 max-w-7xl mx-auto">
          <div className="grid lg:grid-cols-[1fr_2fr] gap-24 items-start">

            <Reveal>
              <div className="lg:sticky" style={{ top: '120px' }}>
                <p
                  style={{
                    fontSize: '10px',
                    letterSpacing: '0.25em',
                    textTransform: 'uppercase',
                    color: '#7B6EF6',
                    marginBottom: '20px',
                  }}
                >
                  Process
                </p>
                <h2
                  className="cinematic-text"
                  style={{
                    fontSize: 'clamp(36px, 4vw, 56px)',
                    lineHeight: 1.05,
                    color: 'var(--text-primary)',
                    marginBottom: '24px',
                  }}
                >
                  Three steps<br />to certainty.
                </h2>
                <p
                  style={{
                    fontSize: '14px',
                    color: 'var(--text-secondary)',
                    lineHeight: 1.8,
                    maxWidth: '260px',
                  }}
                >
                  From raw idea to clear answer. No guesswork. No planning fallacy.
                </p>
              </div>
            </Reveal>

            <div className="space-y-0">
              {STEPS.map(({ n, title, body }, i) => (
                <Reveal key={n} delay={i * 0.12}>
                  <div
                    className="group relative py-12 cursor-default"
                    style={{ borderBottom: '1px solid var(--border-color)' }}
                  >
                    <div className="flex items-start gap-10">
                      <span
                        className="font-display"
                        style={{
                          fontSize: '11px',
                          color: 'rgba(123,110,246,0.5)',
                          letterSpacing: '0.1em',
                          marginTop: '4px',
                          minWidth: '24px',
                        }}
                      >
                        {n}
                      </span>
                      <div className="flex-1">
                        <h3
                          className="font-display"
                          style={{
                            fontSize: '22px',
                            fontWeight: 700,
                            color: 'var(--text-primary)',
                            marginBottom: '12px',
                            letterSpacing: '-0.01em',
                          }}
                        >
                          {title}
                        </h3>
                        <p style={{ fontSize: '14px', color: 'var(--text-secondary)', lineHeight: 1.8 }}>
                          {body}
                        </p>
                      </div>
                      <ArrowUpRight
                        className="w-5 h-5 opacity-0 group-hover:opacity-100 transition-opacity duration-300"
                        style={{ color: '#7B6EF6', marginTop: '4px', flexShrink: 0 }}
                      />
                    </div>
                    <motion.div
                      className="absolute bottom-0 left-0 h-px"
                      style={{ background: '#7B6EF6', width: 0 }}
                      whileHover={{ width: '100%' }}
                      transition={{ duration: 0.4 }}
                    />
                  </div>
                </Reveal>
              ))}
            </div>
          </div>
        </section>

        <CinematicRule />

        {/* ━━━ WHO IT'S FOR ━━━ */}
        <section className="px-8 py-40 max-w-7xl mx-auto">
          <Reveal className="mb-20">
            <p
              style={{
                fontSize: '10px',
                letterSpacing: '0.25em',
                textTransform: 'uppercase',
                color: '#7B6EF6',
                marginBottom: '20px',
              }}
            >
              Who it&apos;s for
            </p>
            <h2
              className="cinematic-text"
              style={{ fontSize: 'clamp(36px, 4vw, 56px)', lineHeight: 1.05, color: 'var(--text-primary)' }}
            >
              Built for people who<br />cannot afford to guess.
            </h2>
          </Reveal>

          <div className="grid md:grid-cols-2 lg:grid-cols-4 gap-px" style={{ background: 'var(--border-color)' }}>
            {WHO.map(({ label, sub }, i) => (
              <Reveal key={label} delay={i * 0.08}>
                <div
                  className="card-cinematic group p-10 cursor-default"
                  style={{ minHeight: '200px', display: 'flex', flexDirection: 'column', justifyContent: 'space-between' }}
                >
                  <div
                    style={{
                      fontSize: '11px',
                      letterSpacing: '0.15em',
                      textTransform: 'uppercase',
                      color: 'rgba(123,110,246,0.6)',
                    }}
                  >
                    {sub}
                  </div>
                  <div>
                    <h3
                      className="font-display"
                      style={{ fontSize: '20px', fontWeight: 700, color: 'var(--text-primary)', lineHeight: 1.2 }}
                    >
                      {label}
                    </h3>
                  </div>
                </div>
              </Reveal>
            ))}
          </div>
        </section>

        <CinematicRule />

        {/* ━━━ STATS ━━━ */}
        <section className="px-8 py-32 max-w-7xl mx-auto">
          <div className="grid grid-cols-2 md:grid-cols-4 gap-px" style={{ background: 'var(--border-color)' }}>
            {STATS.map(({ value, label }, i) => (
              <Reveal key={label} delay={i * 0.06}>
                <div className="card-cinematic p-12 text-center">
                  <div
                    className="font-display mb-3"
                    style={{
                      fontSize: 'clamp(32px, 4vw, 52px)',
                      fontWeight: 800,
                      letterSpacing: '-0.02em',
                      background: 'linear-gradient(135deg, #f0f0f5 0%, rgba(240,240,245,0.4) 100%)',
                      WebkitBackgroundClip: 'text',
                      WebkitTextFillColor: 'transparent',
                      backgroundClip: 'text',
                    }}
                  >
                    {value}
                  </div>
                  <div
                    style={{
                      fontSize: '11px',
                      letterSpacing: '0.15em',
                      textTransform: 'uppercase',
                      color: 'var(--text-secondary)',
                    }}
                  >
                    {label}
                  </div>
                </div>
              </Reveal>
            ))}
          </div>
        </section>

        <CinematicRule />

        {/* ━━━ FINAL CTA ━━━ */}
        <section className="relative px-8 py-52 text-center overflow-hidden">
          <div
            className="spotlight w-[600px] h-[300px] opacity-[0.06]"
            style={{ background: '#7B6EF6', top: '50%', left: '50%', transform: 'translate(-50%,-50%)' }}
          />

          <Reveal>
            <p
              style={{
                fontSize: '10px',
                letterSpacing: '0.25em',
                textTransform: 'uppercase',
                color: '#7B6EF6',
                marginBottom: '32px',
              }}
            >
              Start now
            </p>
            <h2
              className="cinematic-text mb-6"
              style={{ fontSize: 'clamp(44px, 6vw, 88px)', color: 'var(--text-primary)', lineHeight: 1.0 }}
            >
              Your next decision<br />
              <span style={{ color: 'rgba(240,240,245,0.25)' }}>deserves certainty.</span>
            </h2>
            <p
              style={{ fontSize: '15px', color: 'var(--text-secondary)', marginBottom: '48px', fontWeight: 300 }}
            >
              Stop planning. Start simulating.
            </p>
            <Link
              href="/signup"
              className="group inline-flex items-center gap-3 px-10 py-5"
              style={{
                background: '#7B6EF6',
                color: '#fff',
                fontSize: '13px',
                fontWeight: 500,
                letterSpacing: '0.08em',
                textTransform: 'uppercase',
              }}
            >
              Validate your idea free
              <ArrowRight className="w-4 h-4 group-hover:translate-x-1 transition-transform duration-300" />
            </Link>
          </Reveal>
        </section>

        {/* ━━━ FOOTER ━━━ */}
        <footer className="px-8 py-10" style={{ borderTop: '1px solid var(--border-color)' }}>
          <div className="max-w-7xl mx-auto flex flex-col md:flex-row items-center justify-between gap-4">
            <div className="flex items-center gap-2.5">
              <svg width="16" height="16" viewBox="0 0 20 20" fill="none">
                <circle cx="10" cy="10" r="3" fill="#7B6EF6" />
                <circle cx="10" cy="10" r="7" stroke="#7B6EF6" strokeWidth="0.75" opacity="0.35" />
              </svg>
              <span className="font-display font-700" style={{ fontSize: '13px', color: 'var(--text-secondary)' }}>
                TheCee
              </span>
            </div>
            <p style={{ fontSize: '11px', color: 'rgba(90,90,114,0.6)', letterSpacing: '0.05em' }}>
              © 2026 TheCee. Simulate before you build.
            </p>
            <div className="flex items-center gap-8">
              {['Privacy', 'Terms', 'Contact'].map(item => (
                <a
                  key={item}
                  href="#"
                  style={{
                    fontSize: '11px',
                    color: 'var(--text-secondary)',
                    letterSpacing: '0.1em',
                    textTransform: 'uppercase',
                  }}
                  onMouseEnter={e => (e.currentTarget.style.color = '#f0f0f5')}
                  onMouseLeave={e => (e.currentTarget.style.color = 'var(--text-secondary)')}
                >
                  {item}
                </a>
              ))}
            </div>
          </div>
        </footer>

      </div>
    </div>
  )
}
