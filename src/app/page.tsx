'use client'

import React, { useEffect, useRef, useState } from 'react'
import { AnimatePresence, motion, useScroll, useTransform, useSpring, useMotionValue } from 'framer-motion'
import Link from 'next/link'
import { ArrowRight, ChevronDown } from 'lucide-react'

// Functional components
import InlineAuth from '@/components/landing/InlineAuth'
import DossierSpecimen from '@/components/landing/DossierSpecimen'
import ProcessReel from '@/components/landing/ProcessReel'

import { useAuthStore } from '@/store/auth.store'
import { auth as authLib } from '@/lib/auth'
import { useLogout } from '@/hooks/useAuth'

/* ─── DATA & CONSTANTS ──────────────────────────────────────────── */
const PLATES = [
  { n: 'I', kicker: 'Set the type', title: 'Write the idea, in your handwriting', body: 'Plain words on a clean page. No frameworks, no templates. Drop the assumption you are afraid to put on paper — that is the one we are going to test first.' },
  { n: 'II', kicker: 'Run the press', title: 'Send it under thousands of synthetic readers', body: 'Cast assembled, scenarios laid out, the room goes quiet. Your idea runs against markets that do not flatter it — pricing, channel, timing, defection, the lot.' },
  { n: 'III', kicker: 'File the report', title: 'Read the autopsy before you spend a rupee', body: 'Failure modes ranked. Surviving paths drawn. The exact interventions that shift the odds, on the desk in under two minutes.' },
]

/* ─── CUSTOM CURSOR ──────────────────────────────────────────── */
function CustomCursor() {
  const [mousePosition, setMousePosition] = useState({ x: -100, y: -100 })
  const [isHovering, setIsHovering] = useState(false)

  useEffect(() => {
    const updateMousePosition = (e: MouseEvent) => {
      setMousePosition({ x: e.clientX, y: e.clientY })
    }
    const handleMouseOver = (e: MouseEvent) => {
      const target = e.target as HTMLElement
      if (target.tagName.toLowerCase() === 'A' || target.tagName.toLowerCase() === 'BUTTON' || target.closest('a') || target.closest('button')) {
        setIsHovering(true)
      } else {
        setIsHovering(false)
      }
    }
    window.addEventListener('mousemove', updateMousePosition)
    window.addEventListener('mouseover', handleMouseOver)
    return () => {
      window.removeEventListener('mousemove', updateMousePosition)
      window.removeEventListener('mouseover', handleMouseOver)
    }
  }, [])

  return (
    <motion.div
      animate={{
        x: mousePosition.x - (isHovering ? 24 : 8),
        y: mousePosition.y - (isHovering ? 24 : 8),
        scale: isHovering ? 1.5 : 1,
      }}
      transition={{ type: 'spring', stiffness: 500, damping: 28, mass: 0.5 }}
      style={{
        position: 'fixed',
        top: 0,
        left: 0,
        width: isHovering ? 48 : 16,
        height: isHovering ? 48 : 16,
        borderRadius: '50%',
        backgroundColor: isHovering ? 'rgba(192, 57, 43, 0.15)' : 'var(--red)',
        border: isHovering ? '1px solid var(--red)' : 'none',
        pointerEvents: 'none',
        zIndex: 9999,
        mixBlendMode: 'multiply',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
      }}
    >
      {isHovering && <div style={{ width: 4, height: 4, borderRadius: '50%', background: 'var(--red)' }} />}
    </motion.div>
  )
}

/* ─── PARALLAX TEXT HELPER ──────────────────────────────────────────── */
function ParallaxText({ children, baseVelocity = 100 }: { children: string, baseVelocity: number }) {
  const baseX = useMotionValue(0)
  const { scrollY } = useScroll()
  const scrollVelocity = useTransform(scrollY, [0, 1000], [0, 5])
  const smoothVelocity = useSpring(scrollVelocity, { damping: 50, stiffness: 400 })
  const velocityFactor = useTransform(smoothVelocity, [0, 1000], [0, 5], { clamp: false })

  const x = useTransform(baseX, (v) => `${v}%`)
  const directionFactor = useRef<number>(1)

  useEffect(() => {
    const animate = () => {
      const moveBy = directionFactor.current * baseVelocity * 0.02
      baseX.set(baseX.get() + moveBy)
      if (baseX.get() < -50) baseX.set(0)
      else if (baseX.get() > 0) baseX.set(-50)
      requestAnimationFrame(animate)
    }
    const timer = requestAnimationFrame(animate)
    return () => cancelAnimationFrame(timer)
  }, [baseX, baseVelocity])

  return (
    <div style={{ overflow: 'hidden', whiteSpace: 'nowrap', display: 'flex', flexWrap: 'nowrap' }}>
      <motion.div style={{ x, display: 'flex', whiteSpace: 'nowrap' }}>
        <span style={{ display: 'block', marginRight: 40 }}>{children}</span>
        <span style={{ display: 'block', marginRight: 40 }}>{children}</span>
        <span style={{ display: 'block', marginRight: 40 }}>{children}</span>
        <span style={{ display: 'block', marginRight: 40 }}>{children}</span>
      </motion.div>
    </div>
  )
}

/* ─── MASTHEAD ──────────────────────────────────────────── */
function Masthead({ setMenuOpen, setAuthOpen, setAuthMode, isHydrated, isAuthed }: { setMenuOpen: (o: boolean) => void, setAuthOpen: (o: boolean) => void, setAuthMode: (m: 'login' | 'signup') => void, isHydrated: boolean, isAuthed: boolean }) {
  const { scrollYProgress } = useScroll()
  const headerY = useTransform(scrollYProgress, [0, 0.05], [0, -100])
  const opacity = useTransform(scrollYProgress, [0, 0.05], [1, 0])

  return (
    <motion.header
      style={{
        y: headerY,
        opacity,
        position: 'fixed',
        top: 0,
        left: 0,
        right: 0,
        zIndex: 50,
        padding: '24px 48px',
        display: 'flex',
        justifyContent: 'space-between',
        alignItems: 'center',
        borderBottom: '0.5px solid var(--border-color)',
        background: 'transparent',
      }}
    >
      <div style={{ fontSize: 10, letterSpacing: '0.3em', textTransform: 'uppercase', color: 'var(--ink)' }}>
        Vol. I — Issue 04
      </div>
      <div className="font-serif" style={{ fontSize: 32, fontWeight: 900, fontStyle: 'italic', letterSpacing: '-0.04em', color: 'var(--ink)' }}>
        TheCee
      </div>
      <div style={{ display: 'flex', gap: 24, alignItems: 'center' }}>
        {isHydrated && isAuthed ? (
          <Link href="/projects" style={{ fontSize: 11, color: 'var(--paper)', background: 'var(--ink)', padding: '10px 24px', textTransform: 'uppercase', letterSpacing: '0.1em', fontWeight: 600, textDecoration: 'none' }}>
            Enter Press
          </Link>
        ) : (
          <button onClick={() => { setAuthMode('login'); setAuthOpen(true) }} style={{ fontSize: 11, color: 'var(--ink)', background: 'none', border: 'none', textTransform: 'uppercase', letterSpacing: '0.1em', fontWeight: 600, cursor: 'pointer' }}>
            Sign In
          </button>
        )}
      </div>
    </motion.header>
  )
}

/* ─── REVEAL TEXT COMPONENT ──────────────────────────────────────────── */
const SplitText = ({ text, delayOffset = 0 }: { text: string, delayOffset?: number }) => {
  const words = text.split(" ")
  return (
    <span style={{ display: 'inline-block', overflow: 'hidden' }}>
      {words.map((word, i) => (
        <motion.span
          key={i}
          initial={{ y: "120%", opacity: 0, rotate: 5 }}
          whileInView={{ y: 0, opacity: 1, rotate: 0 }}
          viewport={{ once: true, margin: "-100px" }}
          transition={{ duration: 0.8, delay: delayOffset + i * 0.05, ease: [0.2, 0.7, 0.2, 1] }}
          style={{ display: 'inline-block', marginRight: '0.25em', transformOrigin: 'left bottom' }}
        >
          {word}
        </motion.span>
      ))}
    </span>
  )
}

/* ─── MAIN LANDING PAGE ──────────────────────────────────────────── */
export default function LandingPage() {
  const [menuOpen, setMenuOpen] = useState(false)
  const [authOpen, setAuthOpen] = useState(false)
  const [authMode, setAuthMode] = useState<'login' | 'signup'>('login')

  const user = useAuthStore((s) => s.user)
  const isHydrated = useAuthStore((s) => s.isHydrated)
  const isAuthed = Boolean(user) || (isHydrated && typeof window !== 'undefined' && authLib.isAuthenticated())

  const containerRef = useRef(null)
  const { scrollYProgress } = useScroll({ target: containerRef })

  // Parallax values for Hero
  const heroY = useTransform(scrollYProgress, [0, 1], [0, 600])
  const heroScale = useTransform(scrollYProgress, [0, 0.5], [1, 0.9])
  
  // Progress Line
  const progressHeight = useTransform(scrollYProgress, [0, 1], ['0%', '100%'])

  return (
    <div ref={containerRef} style={{ background: 'var(--paper)', minHeight: '100vh', position: 'relative', overflowX: 'hidden' }}>
      <CustomCursor />

      {/* Global Noise Overlay */}
      <div style={{ position: 'fixed', inset: 0, pointerEvents: 'none', zIndex: 9998, opacity: 0.035, backgroundImage: 'url("data:image/svg+xml,%3Csvg viewBox=%220 0 200 200%22 xmlns=%22http://www.w3.org/2000/svg%22%3E%3Cfilter id=%22noise%22%3E%3CfeTurbulence type=%22fractalNoise%22 baseFrequency=%220.65%22 numOctaves=%223%22 stitchTiles=%22stitch%22/%3E%3C/filter%3E%3Crect width=%22100%25%22 height=%22100%25%22 filter=%22url(%23noise)%22/%3E%3C/svg%3E")' }} />

      {/* Vertical Progress Rule */}
      <div style={{ position: 'fixed', top: 0, left: 48, bottom: 0, width: 1, background: 'var(--border-color)', zIndex: 100 }}>
        <motion.div style={{ width: '100%', height: progressHeight, background: 'var(--red)' }} />
      </div>

      <Masthead setMenuOpen={setMenuOpen} setAuthOpen={setAuthOpen} setAuthMode={setAuthMode} isHydrated={isHydrated} isAuthed={isAuthed} />

      {/* ━━━ HERO SECTION ━━━ */}
      <motion.section style={{ y: heroY, scale: heroScale, height: '100vh', display: 'flex', flexDirection: 'column', justifyContent: 'center', padding: '0 120px', position: 'relative' }}>
        <div style={{ marginBottom: 40 }}>
          <motion.div initial={{ scaleX: 0 }} animate={{ scaleX: 1 }} transition={{ duration: 1, ease: "anticipate" }} style={{ width: 120, height: 2, background: 'var(--red)', marginBottom: 20, transformOrigin: 'left' }} />
          <div style={{ fontSize: 12, letterSpacing: '0.4em', textTransform: 'uppercase', color: 'var(--red)', fontWeight: 700 }}>
            <SplitText text="The Behavioral Engine" delayOffset={0.2} />
          </div>
        </div>
        
        <h1 className="font-serif" style={{ fontSize: 'clamp(60px, 10vw, 140px)', lineHeight: 0.9, color: 'var(--ink)', letterSpacing: '-0.04em', fontWeight: 900 }}>
          <SplitText text="Simulate before" delayOffset={0.4} />
          <br />
          <em style={{ color: 'var(--red)', fontStyle: 'italic' }}>
            <SplitText text="you build." delayOffset={0.6} />
          </em>
        </h1>

        <motion.div 
          initial={{ opacity: 0, y: 30 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 1, delay: 1.2 }}
          style={{ marginTop: 60, maxWidth: 500, fontSize: 18, color: 'var(--ink-secondary)', lineHeight: 1.6, fontWeight: 300, fontFamily: 'var(--font-serif)' }}
        >
          We print the autopsy before the burial. 10,000 synthetic readers test your pricing, channel, and narrative. You get the verdict in two minutes.
        </motion.div>

        <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} transition={{ delay: 1.5, duration: 1 }} style={{ marginTop: 60, display: 'flex', gap: 24 }}>
          <button onClick={() => { setAuthMode('signup'); setAuthOpen(true) }} style={{ padding: '20px 40px', background: 'var(--ink)', color: 'var(--paper)', border: 'none', fontSize: 12, letterSpacing: '0.2em', textTransform: 'uppercase', fontWeight: 700, cursor: 'pointer', display: 'flex', alignItems: 'center', gap: 12 }}>
            Run the press <ArrowRight size={16} />
          </button>
        </motion.div>
      </motion.section>

      {/* ━━━ MASSIVE MARQUEE ━━━ */}
      <section style={{ padding: '40px 0', borderTop: '0.5px solid var(--border-color)', borderBottom: '0.5px solid var(--border-color)', background: 'var(--paper-dark)', overflow: 'hidden' }}>
        <div className="font-serif" style={{ fontSize: 'clamp(80px, 12vw, 200px)', fontWeight: 900, fontStyle: 'italic', color: 'var(--ink)', opacity: 0.05, whiteSpace: 'nowrap' }}>
          <ParallaxText baseVelocity={-2}>THE CEE · SIMULATION BROADSHEET · </ParallaxText>
        </div>
      </section>

      {/* ━━━ THE MANIFESTO ━━━ */}
      <section style={{ padding: '200px 120px', background: 'var(--paper)', position: 'relative' }}>
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1.5fr', gap: 100 }}>
          <motion.div initial={{ opacity: 0, x: -50 }} whileInView={{ opacity: 1, x: 0 }} viewport={{ once: true, margin: "-200px" }} transition={{ duration: 1 }}>
            <div className="font-serif numeral" style={{ fontSize: 180, lineHeight: 0.8, color: 'var(--red)', opacity: 0.2, fontStyle: 'italic' }}>I.</div>
            <h2 className="font-serif" style={{ fontSize: 48, fontWeight: 900, color: 'var(--ink)', marginTop: 20 }}>
              The honest founder needs no advice.
            </h2>
          </motion.div>
          <div style={{ fontSize: 24, lineHeight: 1.6, color: 'var(--ink-secondary)', fontFamily: 'var(--font-serif)', columnCount: 2, columnGap: 60, fontWeight: 300 }}>
            <p style={{ marginBottom: 30 }}>
              <span style={{ float: 'left', fontSize: 80, lineHeight: 0.8, paddingTop: 10, paddingRight: 10, color: 'var(--ink)', fontWeight: 900 }}>W</span>e built a room full of a thousand quiet strangers who will look at your idea and, without flattery, tell you where it will break. 
            </p>
            <p style={{ marginBottom: 30 }}>
              On the other side of the simulation, a cohort of synthetic readers — priced, placed, suspicious, bored, loyal, or bored-and-loyal — vote on your pricing, your channel, your timing, and your story. They do not flatter you.
            </p>
            <p>
              We print what they said. You read the autopsy before the burial. Then you decide whether to build. That is the whole magazine, in a sentence.
            </p>
          </div>
        </div>
      </section>

      {/* ━━━ DOSSIER SPECIMEN (Wrapped) ━━━ */}
      <section style={{ padding: '160px 48px', background: 'var(--ink)', color: 'var(--paper)', overflow: 'hidden' }}>
        <div style={{ maxWidth: 1400, margin: '0 auto' }}>
          <motion.div initial={{ opacity: 0, y: 50 }} whileInView={{ opacity: 1, y: 0 }} viewport={{ once: true }} transition={{ duration: 1 }}>
            <div style={{ fontSize: 12, letterSpacing: '0.4em', textTransform: 'uppercase', color: 'var(--red)', fontWeight: 700, marginBottom: 20 }}>
              The Index
            </div>
            <h2 className="font-serif" style={{ fontSize: 'clamp(50px, 8vw, 100px)', fontWeight: 900, fontStyle: 'italic', letterSpacing: '-0.02em', marginBottom: 80 }}>
              Your ideas, <span style={{ color: 'var(--red)' }}>under review.</span>
            </h2>
          </motion.div>
          
          <motion.div
            initial={{ rotateX: 20, y: 100, opacity: 0 }}
            whileInView={{ rotateX: 0, y: 0, opacity: 1 }}
            viewport={{ once: true, margin: "-100px" }}
            transition={{ type: "spring", stiffness: 40, damping: 20 }}
            style={{ perspective: 1200 }}
          >
            <div style={{ background: 'var(--paper)', padding: 40, borderRadius: 2 }}>
              <DossierSpecimen />
            </div>
          </motion.div>
        </div>
      </section>

      {/* ━━━ THE PROCESS REEL ━━━ */}
      <section style={{ padding: '160px 0', background: 'var(--paper-dark)' }}>
        <div style={{ maxWidth: 1280, margin: '0 auto', padding: '0 48px' }}>
          <motion.h2 
            initial={{ opacity: 0 }} 
            whileInView={{ opacity: 1 }} 
            viewport={{ once: true }}
            className="font-serif" 
            style={{ fontSize: 80, fontWeight: 900, textAlign: 'center', marginBottom: 100, color: 'var(--ink)', letterSpacing: '-0.03em' }}
          >
            The Press Cycle
          </motion.h2>
        </div>
        <ProcessReel plates={PLATES} />
      </section>

      {/* ━━━ DISTRIBUTION / FUTURES ━━━ */}
      <section style={{ padding: '200px 120px', background: 'var(--paper)' }}>
        <div style={{ maxWidth: 1280, margin: '0 auto' }}>
          <motion.div initial={{ opacity: 0, y: 30 }} whileInView={{ opacity: 1, y: 0 }} viewport={{ once: true }} transition={{ duration: 0.8 }}>
            <div style={{ height: 2, width: 40, background: 'var(--red)', marginBottom: 20 }} />
            <h2 className="font-serif" style={{ fontSize: 72, fontWeight: 900, color: 'var(--ink)', lineHeight: 1, marginBottom: 80 }}>
              Every idea has a shape.<br/>
              <span style={{ fontStyle: 'italic', color: 'var(--red)' }}>We show you yours.</span>
            </h2>
          </motion.div>

          {/* Extreme animated distribution bars */}
          <div style={{ display: 'flex', flexDirection: 'column', gap: 20 }}>
            {[
              { label: 'Dies fast', pct: 14, color: 'var(--ink)' },
              { label: 'Quiet death', pct: 23, color: '#5a4e42' },
              { label: 'Pivots', pct: 31, color: 'var(--red)' },
              { label: 'Survives', pct: 22, color: '#786e48' },
              { label: 'Scales', pct: 10, color: '#3a5a48' },
            ].map((d, i) => (
              <div key={d.label} style={{ display: 'flex', alignItems: 'center', gap: 40 }}>
                <div style={{ width: 140, fontSize: 14, fontWeight: 700, textTransform: 'uppercase', letterSpacing: '0.2em', color: d.color }}>
                  {d.label}
                </div>
                <div style={{ flex: 1, height: 2, background: 'rgba(26,23,20,0.1)', position: 'relative' }}>
                  <motion.div
                    initial={{ width: 0 }}
                    whileInView={{ width: `${d.pct}%` }}
                    viewport={{ once: true }}
                    transition={{ duration: 1.5, delay: i * 0.2, ease: [0.16, 1, 0.3, 1] }}
                    style={{ position: 'absolute', top: -10, bottom: -10, left: 0, background: d.color }}
                  >
                    <motion.span 
                      initial={{ opacity: 0 }}
                      whileInView={{ opacity: 1 }}
                      transition={{ delay: 1.5 + i * 0.2 }}
                      className="font-serif"
                      style={{ position: 'absolute', right: 20, top: '50%', transform: 'translateY(-50%)', color: 'var(--paper)', fontSize: 16, fontWeight: 800, fontStyle: 'italic' }}
                    >
                      {d.pct}%
                    </motion.span>
                  </motion.div>
                </div>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* ━━━ FOOTER / FINAL CTA ━━━ */}
      <section style={{ background: 'var(--ink)', padding: '160px 48px', color: 'var(--paper)', position: 'relative', overflow: 'hidden' }}>
        <div style={{ position: 'absolute', inset: 0, backgroundImage: 'radial-gradient(circle at center, rgba(192,57,43,0.1) 0%, transparent 70%)' }} />
        
        <div style={{ maxWidth: 1280, margin: '0 auto', textAlign: 'center', position: 'relative', zIndex: 10 }}>
          <motion.div initial={{ scale: 0.9, opacity: 0 }} whileInView={{ scale: 1, opacity: 1 }} transition={{ duration: 1, ease: "easeOut" }} viewport={{ once: true }}>
            <h2 className="font-serif" style={{ fontSize: 'clamp(60px, 8vw, 120px)', fontWeight: 900, fontStyle: 'italic', letterSpacing: '-0.02em', marginBottom: 40 }}>
              Stop guessing.<br/>Start simulating.
            </h2>
            <button onClick={() => { setAuthMode('signup'); setAuthOpen(true) }} style={{ padding: '24px 60px', background: 'var(--red)', color: 'var(--paper)', border: 'none', fontSize: 14, letterSpacing: '0.3em', textTransform: 'uppercase', fontWeight: 800, cursor: 'pointer', transition: 'transform 0.3s', boxShadow: '0 20px 40px rgba(192,57,43,0.3)' }} onMouseEnter={e => e.currentTarget.style.transform = 'scale(1.05)'} onMouseLeave={e => e.currentTarget.style.transform = 'scale(1)'}>
              Run Your First Dossier
            </button>
          </motion.div>
        </div>

        <div style={{ maxWidth: 1280, margin: '200px auto 0', display: 'flex', justifyContent: 'space-between', borderTop: '0.5px solid rgba(242,236,224,0.1)', paddingTop: 40, fontSize: 10, letterSpacing: '0.3em', textTransform: 'uppercase', color: 'rgba(242,236,224,0.4)' }}>
          <span>© 2026 TheCee</span>
          <span>Set in Playfair & DM Sans</span>
        </div>
      </section>

      {/* ━━━ INLINE AUTH ━━━ */}
      <InlineAuth open={authOpen} onClose={() => setAuthOpen(false)} initialMode={authMode} />
    </div>
  )
}
