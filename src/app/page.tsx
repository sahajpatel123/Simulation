'use client'

import React, { useEffect, useRef, useState } from 'react'
import { motion, useScroll, useTransform, useSpring, useMotionValue, useMotionTemplate, AnimatePresence } from 'framer-motion'
import Link from 'next/link'
import { ArrowRight, Crosshair } from 'lucide-react'

// Functional components
import InlineAuth from '@/components/landing/InlineAuth'
import DossierSpecimen from '@/components/landing/DossierSpecimen'

import { useAuthStore } from '@/store/auth.store'
import { auth as authLib } from '@/lib/auth'

/* ─── DATA & CONSTANTS ──────────────────────────────────────────── */
const PLATES = [
  { n: 'I', kicker: 'Set the type', title: 'Write the idea, in your handwriting', body: 'Plain words on a clean page. No frameworks, no templates. Drop the assumption you are afraid to put on paper — that is the one we are going to test first.' },
  { n: 'II', kicker: 'Run the press', title: 'Send it under thousands of synthetic readers', body: 'Cast assembled, scenarios laid out, the room goes quiet. Your idea runs against markets that do not flatter it — pricing, channel, timing, defection, the lot.' },
  { n: 'III', kicker: 'File the report', title: 'Read the autopsy before you spend a rupee', body: 'Failure modes ranked. Surviving paths drawn. The exact interventions that shift the odds, on the desk in under two minutes.' },
]

/* ─── LIQUID INK CURSOR & SVG FILTERS ──────────────────────────────────────────── */
function SVGFilters() {
  return (
    <svg style={{ position: 'absolute', width: 0, height: 0 }} aria-hidden="true">
      <defs>
        <filter id="goo">
          <feGaussianBlur in="SourceGraphic" stdDeviation="8" result="blur" />
          <feColorMatrix in="blur" mode="matrix" values="1 0 0 0 0  0 1 0 0 0  0 0 1 0 0  0 0 0 25 -9" result="goo" />
          <feComposite in="SourceGraphic" in2="goo" operator="atop" />
        </filter>
        <filter id="chromatic">
          <feOffset dx="4" dy="0" in="SourceGraphic" result="red-shift" />
          <feOffset dx="-4" dy="0" in="SourceGraphic" result="blue-shift" />
          <feMerge>
            <feMergeNode in="red-shift" />
            <feMergeNode in="blue-shift" />
            <feMergeNode in="SourceGraphic" />
          </feMerge>
        </filter>
      </defs>
    </svg>
  )
}

function LiquidCursor() {
  const mouseX = useMotionValue(-100)
  const mouseY = useMotionValue(-100)
  const [isHovering, setIsHovering] = useState(false)

  useEffect(() => {
    const updateMouse = (e: MouseEvent) => {
      mouseX.set(e.clientX)
      mouseY.set(e.clientY)
    }
    const handleHover = (e: MouseEvent) => {
      const target = e.target as HTMLElement
      if (target.tagName.toLowerCase() === 'A' || target.tagName.toLowerCase() === 'BUTTON' || target.closest('a') || target.closest('button')) {
        setIsHovering(true)
      } else {
        setIsHovering(false)
      }
    }
    window.addEventListener('mousemove', updateMouse)
    window.addEventListener('mouseover', handleHover)
    return () => {
      window.removeEventListener('mousemove', updateMouse)
      window.removeEventListener('mouseover', handleHover)
    }
  }, [mouseX, mouseY])

  return (
    <div style={{ position: 'fixed', inset: 0, pointerEvents: 'none', zIndex: 9999, filter: 'url(#goo)' }}>
      <motion.div
        style={{
          position: 'absolute',
          width: 32,
          height: 32,
          borderRadius: '50%',
          background: 'var(--red)',
          x: useTransform(mouseX, x => x - 16),
          y: useTransform(mouseY, y => y - 16),
          scale: isHovering ? 2.5 : 1,
        }}
        transition={{ type: 'spring', stiffness: 400, damping: 28, mass: 0.5 }}
      />
      <motion.div
        style={{
          position: 'absolute',
          width: 12,
          height: 12,
          borderRadius: '50%',
          background: '#0a0a0a',
          x: useTransform(mouseX, x => x - 6),
          y: useTransform(mouseY, y => y - 6),
          scale: isHovering ? 0 : 1,
        }}
        transition={{ type: 'spring', stiffness: 500, damping: 20 }}
      />
    </div>
  )
}

/* ─── MECHANICAL STAMP TEXT ──────────────────────────────────────────── */
function MechanicalStamp({ children, delay = 0, style = {} }: { children: React.ReactNode, delay?: number, style?: React.CSSProperties }) {
  return (
    <motion.div
      initial={{ scale: 3, opacity: 0, filter: 'blur(10px)', color: 'var(--red)', y: -50 }}
      whileInView={{ scale: 1, opacity: 1, filter: 'blur(0px)', color: 'var(--ink)', y: 0 }}
      viewport={{ once: true, margin: '-100px' }}
      transition={{ type: 'spring', stiffness: 300, damping: 10, mass: 1, delay }}
      style={{ display: 'inline-block', transformOrigin: 'center center', ...style }}
    >
      {children}
    </motion.div>
  )
}

/* ─── MASTHEAD ──────────────────────────────────────────── */
function Masthead({ setAuthOpen, setAuthMode, isHydrated, isAuthed }: { setAuthOpen: (o: boolean) => void, setAuthMode: (m: 'login' | 'signup') => void, isHydrated: boolean, isAuthed: boolean }) {
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
        mixBlendMode: 'difference',
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
          <Link href="/projects" style={{ fontSize: 11, color: 'var(--paper)', background: 'var(--ink)', padding: '10px 24px', textTransform: 'uppercase', letterSpacing: '0.1em', fontWeight: 900, textDecoration: 'none' }}>
            Enter Press
          </Link>
        ) : (
          <button onClick={() => { setAuthMode('login'); setAuthOpen(true) }} style={{ fontSize: 11, color: 'var(--ink)', background: 'none', border: 'none', textTransform: 'uppercase', letterSpacing: '0.1em', fontWeight: 900, cursor: 'pointer' }}>
            Sign In
          </button>
        )}
      </div>
    </motion.header>
  )
}

/* ─── FLASHLIGHT REVEAL ROOM ──────────────────────────────────────────── */
function FlashlightRoom() {
  const containerRef = useRef<HTMLDivElement>(null)
  const mouseX = useMotionValue(0)
  const mouseY = useMotionValue(0)

  const handleMouseMove = (e: React.MouseEvent<HTMLDivElement>) => {
    const rect = containerRef.current?.getBoundingClientRect()
    if (rect) {
      mouseX.set(e.clientX - rect.left)
      mouseY.set(e.clientY - rect.top)
    }
  }

  const maskImage = useMotionTemplate`radial-gradient(600px circle at ${mouseX}px ${mouseY}px, black 0%, transparent 100%)`

  return (
    <section 
      ref={containerRef}
      onMouseMove={handleMouseMove}
      style={{ 
        position: 'relative', 
        padding: '200px 120px', 
        background: '#050505', 
        minHeight: '120vh',
        cursor: 'none',
        overflow: 'hidden'
      }}
    >
      {/* Background (Dim text) */}
      <div style={{ maxWidth: 1400, margin: '0 auto', color: '#1a1a1a' }}>
        <h2 className="font-serif" style={{ fontSize: 'clamp(60px, 10vw, 160px)', fontWeight: 900, lineHeight: 0.85, letterSpacing: '-0.04em' }}>
          Every idea<br/>has a shape.<br/>
          <span style={{ fontStyle: 'italic' }}>We show you yours.</span>
        </h2>
        
        <div style={{ marginTop: 120, display: 'grid', gridTemplateColumns: 'repeat(5, 1fr)', gap: 40, fontFamily: 'var(--font-mono)' }}>
          {[
            { label: 'Dies fast', pct: 14 },
            { label: 'Quiet death', pct: 23 },
            { label: 'Pivots', pct: 31 },
            { label: 'Survives', pct: 22 },
            { label: 'Scales', pct: 10 },
          ].map((d) => (
            <div key={d.label}>
              <div style={{ fontSize: 14, textTransform: 'uppercase', letterSpacing: '0.2em', marginBottom: 20 }}>{d.label}</div>
              <div className="font-serif" style={{ fontSize: 80, fontStyle: 'italic', fontWeight: 900 }}>{d.pct}%</div>
            </div>
          ))}
        </div>
      </div>

      {/* Foreground (Bright text revealed by flashlight mask) */}
      <motion.div
        style={{
          position: 'absolute',
          inset: 0,
          padding: '200px 120px',
          background: '#050505',
          color: 'var(--paper)',
          maskImage,
          WebkitMaskImage: maskImage,
          pointerEvents: 'none',
        }}
      >
        <div style={{ maxWidth: 1400, margin: '0 auto' }}>
          <h2 className="font-serif" style={{ fontSize: 'clamp(60px, 10vw, 160px)', fontWeight: 900, lineHeight: 0.85, letterSpacing: '-0.04em' }}>
            Every idea<br/>has a shape.<br/>
            <span style={{ fontStyle: 'italic', color: 'var(--red)' }}>We show you yours.</span>
          </h2>
          
          <div style={{ marginTop: 120, display: 'grid', gridTemplateColumns: 'repeat(5, 1fr)', gap: 40, fontFamily: 'var(--font-mono)' }}>
            {[
              { label: 'Dies fast', pct: 14 },
              { label: 'Quiet death', pct: 23 },
              { label: 'Pivots', pct: 31 },
              { label: 'Survives', pct: 22 },
              { label: 'Scales', pct: 10 },
            ].map((d) => (
              <div key={d.label}>
                <div style={{ fontSize: 14, textTransform: 'uppercase', letterSpacing: '0.2em', marginBottom: 20, color: 'var(--red)' }}>{d.label}</div>
                <div className="font-serif" style={{ fontSize: 80, fontStyle: 'italic', fontWeight: 900 }}>{d.pct}%</div>
              </div>
            ))}
          </div>
        </div>
      </motion.div>
    </section>
  )
}

/* ─── INFINITE RIBBON ──────────────────────────────────────────── */
function InfiniteRibbon({ text, velocity = 100 }: { text: string, velocity?: number }) {
  const baseX = useMotionValue(0)
  const { scrollY } = useScroll()
  const scrollVelocity = useTransform(scrollY, [0, 1000], [0, 5])
  const smoothVelocity = useSpring(scrollVelocity, { damping: 50, stiffness: 400 })
  const x = useTransform(baseX, (v) => `${v}%`)
  const directionFactor = useRef<number>(1)

  useEffect(() => {
    const animate = () => {
      const moveBy = directionFactor.current * velocity * 0.02
      baseX.set(baseX.get() + moveBy)
      if (baseX.get() < -50) baseX.set(0)
      else if (baseX.get() > 0) baseX.set(-50)
      requestAnimationFrame(animate)
    }
    const timer = requestAnimationFrame(animate)
    return () => cancelAnimationFrame(timer)
  }, [baseX, velocity])

  return (
    <div style={{ overflow: 'hidden', whiteSpace: 'nowrap', display: 'flex', background: 'var(--red)', color: 'var(--paper)', padding: '20px 0', transform: 'rotate(-2deg) scale(1.1)', boxShadow: '0 20px 40px rgba(0,0,0,0.2)', position: 'relative', zIndex: 10 }}>
      <motion.div style={{ x, display: 'flex', whiteSpace: 'nowrap' }}>
        {[...Array(6)].map((_, i) => (
          <span key={i} className="font-serif" style={{ display: 'block', marginRight: 80, fontSize: 40, fontWeight: 900, fontStyle: 'italic', letterSpacing: '-0.02em', textTransform: 'uppercase' }}>
            {text}
          </span>
        ))}
      </motion.div>
    </div>
  )
}

/* ─── MAIN LANDING PAGE ──────────────────────────────────────────── */
export default function LandingPage() {
  const [authOpen, setAuthOpen] = useState(false)
  const [authMode, setAuthMode] = useState<'login' | 'signup'>('login')

  const user = useAuthStore((s) => s.user)
  const isHydrated = useAuthStore((s) => s.isHydrated)
  const isAuthed = Boolean(user) || (isHydrated && typeof window !== 'undefined' && authLib.isAuthenticated())

  const containerRef = useRef(null)
  const { scrollYProgress } = useScroll({ target: containerRef })

  // Parallax Hero
  const heroY = useTransform(scrollYProgress, [0, 1], [0, 800])
  const heroOpacity = useTransform(scrollYProgress, [0, 0.2], [1, 0])

  return (
    <div ref={containerRef} style={{ background: 'var(--paper)', minHeight: '100vh', position: 'relative', overflowX: 'hidden' }}>
      <SVGFilters />
      <LiquidCursor />

      {/* Extreme Film Grain */}
      <div style={{ position: 'fixed', inset: 0, pointerEvents: 'none', zIndex: 9998, opacity: 0.05, backgroundImage: 'url("data:image/svg+xml,%3Csvg viewBox=%220 0 200 200%22 xmlns=%22http://www.w3.org/2000/svg%22%3E%3Cfilter id=%22noise%22%3E%3CfeTurbulence type=%22fractalNoise%22 baseFrequency=%220.8%22 numOctaves=%224%22 stitchTiles=%22stitch%22/%3E%3C/filter%3E%3Crect width=%22100%25%22 height=%22100%25%22 filter=%22url(%23noise)%22/%3E%3C/svg%3E")' }} />

      <Masthead setAuthOpen={setAuthOpen} setAuthMode={setAuthMode} isHydrated={isHydrated} isAuthed={isAuthed} />

      {/* ━━━ SECTION 1: THE INK DROP HERO ━━━ */}
      <motion.section style={{ y: heroY, opacity: heroOpacity, height: '100vh', display: 'flex', flexDirection: 'column', justifyContent: 'center', padding: '0 120px', position: 'relative' }}>
        
        {/* Giant structural ink drops in background */}
        <div style={{ position: 'absolute', top: '10%', right: '10%', filter: 'url(#goo)' }}>
          <motion.div animate={{ y: [0, -20, 0], scale: [1, 1.1, 1] }} transition={{ duration: 4, repeat: Infinity, ease: 'easeInOut' }} style={{ width: 400, height: 400, background: 'var(--red)', borderRadius: '50%', position: 'absolute', opacity: 0.03 }} />
        </div>

        <div style={{ overflow: 'hidden' }}>
          <MechanicalStamp delay={0.2} style={{ fontSize: 14, letterSpacing: '0.4em', textTransform: 'uppercase', color: 'var(--red)', fontWeight: 900, marginBottom: 40, borderLeft: '4px solid var(--red)', paddingLeft: 16 }}>
            The Behavioral Simulation Engine
          </MechanicalStamp>
        </div>
        
        <h1 className="font-serif" style={{ fontSize: 'clamp(80px, 12vw, 200px)', lineHeight: 0.85, letterSpacing: '-0.05em', fontWeight: 900, color: 'var(--ink)' }}>
          <MechanicalStamp delay={0.4}>Simulate</MechanicalStamp><br />
          <MechanicalStamp delay={0.6}>before</MechanicalStamp><br />
          <em style={{ color: 'var(--red)', fontStyle: 'italic', paddingRight: '20px' }}>
            <MechanicalStamp delay={0.8}>you build.</MechanicalStamp>
          </em>
        </h1>

        <motion.div initial={{ opacity: 0, clipPath: 'inset(0 100% 0 0)' }} animate={{ opacity: 1, clipPath: 'inset(0 0% 0 0)' }} transition={{ duration: 1.5, delay: 1.2, ease: [0.77, 0, 0.175, 1] }} style={{ marginTop: 80, display: 'flex', alignItems: 'center', gap: 40 }}>
          <button onClick={() => { setAuthMode('signup'); setAuthOpen(true) }} style={{ padding: '24px 48px', background: 'var(--ink)', color: 'var(--paper)', border: 'none', fontSize: 14, letterSpacing: '0.3em', textTransform: 'uppercase', fontWeight: 900, cursor: 'pointer', display: 'flex', alignItems: 'center', gap: 16, transition: 'all 0.3s' }}>
            Run the press <ArrowRight size={20} />
          </button>
          <div style={{ maxWidth: 400, fontSize: 16, color: 'var(--ink-secondary)', lineHeight: 1.6, fontWeight: 500, fontFamily: 'var(--font-serif)', fontStyle: 'italic' }}>
            We print the autopsy before the burial. 10,000 synthetic readers test your pricing, channel, and narrative.
          </div>
        </motion.div>
      </motion.section>

      <InfiniteRibbon text="The honest founder needs no advice." velocity={-2} />

      {/* ━━━ SECTION 2: THE MECHANICAL MANIFESTO ━━━ */}
      <section style={{ padding: '240px 120px', background: 'var(--paper)' }}>
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1.5fr', gap: 120 }}>
          <div>
            <MechanicalStamp style={{ fontSize: 240, lineHeight: 0.8, color: 'var(--red)', opacity: 0.15, fontStyle: 'italic', fontFamily: 'var(--font-serif)' }}>
              I.
            </MechanicalStamp>
            <motion.h2 initial={{ opacity: 0, x: -50 }} whileInView={{ opacity: 1, x: 0 }} viewport={{ once: true }} transition={{ duration: 1 }} className="font-serif" style={{ fontSize: 56, fontWeight: 900, color: 'var(--ink)', marginTop: 40, lineHeight: 1.1, letterSpacing: '-0.02em' }}>
              The press <br/><span style={{ color: 'var(--red)' }}>does not flatter.</span>
            </motion.h2>
          </div>
          <div style={{ fontSize: 32, lineHeight: 1.5, color: 'var(--ink)', fontFamily: 'var(--font-serif)', fontWeight: 300, columnCount: 2, columnGap: 80 }}>
            <p style={{ marginBottom: 40 }}>
              <span style={{ float: 'left', fontSize: 120, lineHeight: 0.8, paddingTop: 12, paddingRight: 20, color: 'var(--ink)', fontWeight: 900 }}>W</span>e built a room full of a thousand quiet strangers who will look at your idea and, without flattery, tell you exactly where it will break. 
            </p>
            <p style={{ marginBottom: 40 }}>
              On the other side of the simulation, a cohort of synthetic readers — priced, placed, suspicious, bored, loyal, or bored-and-loyal — vote on your pricing, your channel, your timing, and your story. 
            </p>
            <p>
              We print what they said. You read the autopsy before the burial. Then you decide whether to build. That is the whole magazine, in a sentence.
            </p>
          </div>
        </div>
      </section>

      {/* ━━━ SECTION 3: THE FLASHLIGHT REVEAL (DISTRIBUTION) ━━━ */}
      <FlashlightRoom />

      {/* ━━━ SECTION 4: THE CINEMATIC DOSSIER SPECIMEN ━━━ */}
      <section style={{ padding: '240px 120px', background: 'var(--paper)', position: 'relative' }}>
        {/* Giant Red Watermark */}
        <div style={{ position: 'absolute', top: '10%', left: '5%', fontSize: '400px', fontWeight: 900, color: 'var(--red)', opacity: 0.03, zIndex: 0, fontFamily: 'var(--font-serif)', fontStyle: 'italic', pointerEvents: 'none' }}>
          Specimen
        </div>

        <div style={{ maxWidth: 1400, margin: '0 auto', position: 'relative', zIndex: 10 }}>
          <motion.div initial={{ opacity: 0, y: 100 }} whileInView={{ opacity: 1, y: 0 }} viewport={{ once: true }} transition={{ duration: 1, ease: [0.16, 1, 0.3, 1] }}>
            <div style={{ fontSize: 14, letterSpacing: '0.4em', textTransform: 'uppercase', color: 'var(--red)', fontWeight: 900, marginBottom: 30, borderLeft: '4px solid var(--red)', paddingLeft: 16 }}>
              The Index
            </div>
            <h2 className="font-serif" style={{ fontSize: 'clamp(60px, 10vw, 140px)', fontWeight: 900, fontStyle: 'italic', letterSpacing: '-0.04em', marginBottom: 120, lineHeight: 0.9 }}>
              Your ideas,<br/>
              <span style={{ color: 'var(--red)' }}>under review.</span>
            </h2>
          </motion.div>
          
          <motion.div
            initial={{ rotateX: 30, rotateY: 10, y: 200, opacity: 0, scale: 0.9 }}
            whileInView={{ rotateX: 0, rotateY: 0, y: 0, opacity: 1, scale: 1 }}
            viewport={{ once: true, margin: "-100px" }}
            transition={{ type: "spring", stiffness: 100, damping: 30, mass: 2 }}
            style={{ perspective: 2000, transformStyle: 'preserve-3d' }}
          >
            <div style={{ background: 'var(--paper)', padding: 60, border: '1px solid var(--ink)', boxShadow: '0 60px 120px rgba(0,0,0,0.15), 0 20px 40px rgba(0,0,0,0.1)' }}>
              <DossierSpecimen />
            </div>
          </motion.div>
        </div>
      </section>

      {/* ━━━ FINAL CTA: THE MASSIVE STAMP ━━━ */}
      <section style={{ background: 'var(--red)', padding: '240px 120px', color: 'var(--paper)', position: 'relative', overflow: 'hidden' }}>
        {/* Ink Bleed Physics Background */}
        <div style={{ position: 'absolute', inset: 0, filter: 'url(#goo)', zIndex: 0 }}>
          <motion.div animate={{ scale: [1, 1.5, 1], rotate: [0, 90, 0] }} transition={{ duration: 20, repeat: Infinity, ease: 'linear' }} style={{ position: 'absolute', top: '-50%', left: '-20%', width: '100%', height: '200%', background: '#a93226', borderRadius: '40%' }} />
          <motion.div animate={{ scale: [1.5, 1, 1.5], rotate: [0, -90, 0] }} transition={{ duration: 25, repeat: Infinity, ease: 'linear' }} style={{ position: 'absolute', top: '-30%', right: '-20%', width: '100%', height: '200%', background: '#922b21', borderRadius: '45%' }} />
        </div>
        
        <div style={{ maxWidth: 1400, margin: '0 auto', textAlign: 'center', position: 'relative', zIndex: 10 }}>
          <motion.div initial={{ scale: 0.8, opacity: 0, filter: 'blur(20px)' }} whileInView={{ scale: 1, opacity: 1, filter: 'blur(0px)' }} transition={{ duration: 1.5, ease: [0.16, 1, 0.3, 1] }} viewport={{ once: true }}>
            <div style={{ fontSize: 14, letterSpacing: '0.4em', textTransform: 'uppercase', color: 'var(--paper)', fontWeight: 900, marginBottom: 40, opacity: 0.8 }}>
              The verdict awaits
            </div>
            <h2 className="font-serif" style={{ fontSize: 'clamp(80px, 12vw, 200px)', fontWeight: 900, fontStyle: 'italic', letterSpacing: '-0.04em', marginBottom: 80, lineHeight: 0.9 }}>
              Stop guessing.<br/>Start simulating.
            </h2>
            <button onClick={() => { setAuthMode('signup'); setAuthOpen(true) }} style={{ padding: '32px 80px', background: 'var(--ink)', color: 'var(--paper)', border: 'none', fontSize: 16, letterSpacing: '0.4em', textTransform: 'uppercase', fontWeight: 900, cursor: 'pointer', transition: 'all 0.4s cubic-bezier(0.16, 1, 0.3, 1)', boxShadow: '0 40px 80px rgba(0,0,0,0.4)' }} onMouseEnter={e => { e.currentTarget.style.transform = 'scale(1.1) translateY(-10px)'; e.currentTarget.style.background = '#fff'; e.currentTarget.style.color = 'var(--red)' }} onMouseLeave={e => { e.currentTarget.style.transform = 'scale(1) translateY(0)'; e.currentTarget.style.background = 'var(--ink)'; e.currentTarget.style.color = 'var(--paper)' }}>
              Run Your First Dossier
            </button>
          </motion.div>
        </div>

        <div style={{ maxWidth: 1400, margin: '200px auto 0', display: 'flex', justifyContent: 'space-between', borderTop: '2px solid rgba(255,255,255,0.1)', paddingTop: 40, fontSize: 12, letterSpacing: '0.3em', textTransform: 'uppercase', color: 'rgba(255,255,255,0.6)', fontWeight: 900, position: 'relative', zIndex: 10 }}>
          <span>© 2026 TheCee</span>
          <span>Printed in IST</span>
        </div>
      </section>

      {/* ━━━ INLINE AUTH ━━━ */}
      <InlineAuth open={authOpen} onClose={() => setAuthOpen(false)} initialMode={authMode} />
    </div>
  )
}
