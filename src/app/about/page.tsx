'use client'

import React, { useRef } from 'react'
import { motion, useScroll, useTransform } from 'framer-motion'
import Link from 'next/link'
import { ArrowLeft } from 'lucide-react'

export default function AboutPage() {
  const ref = useRef(null)
  const { scrollYProgress } = useScroll({ target: ref, offset: ['start start', 'end end'] })
  
  // Dramatic color shift from ink black to paper
  const bg = useTransform(scrollYProgress, [0, 0.4, 0.6, 1], ['#050505', '#050505', 'var(--paper)', 'var(--paper)'])
  const textColor = useTransform(scrollYProgress, [0, 0.4, 0.6, 1], ['var(--paper)', 'var(--paper)', 'var(--ink)', 'var(--ink)'])
  const accentColor = useTransform(scrollYProgress, [0, 0.5], ['var(--paper)', 'var(--red)'])

  // Floating text blocks
  const y1 = useTransform(scrollYProgress, [0, 0.3], [0, -200])
  const o1 = useTransform(scrollYProgress, [0, 0.2, 0.3], [1, 1, 0])
  const blur1 = useTransform(scrollYProgress, [0.2, 0.3], ['blur(0px)', 'blur(20px)'])

  const y2 = useTransform(scrollYProgress, [0.2, 0.5, 0.7], [200, 0, -200])
  const o2 = useTransform(scrollYProgress, [0.2, 0.4, 0.6, 0.7], [0, 1, 1, 0])
  const blur2 = useTransform(scrollYProgress, [0.2, 0.4, 0.6, 0.7], ['blur(20px)', 'blur(0px)', 'blur(0px)', 'blur(20px)'])

  const y3 = useTransform(scrollYProgress, [0.6, 0.8, 1], [200, 0, 0])
  const o3 = useTransform(scrollYProgress, [0.6, 0.8, 1], [0, 1, 1])
  const blur3 = useTransform(scrollYProgress, [0.6, 0.8, 1], ['blur(20px)', 'blur(0px)', 'blur(0px)'])

  return (
    <motion.main ref={ref} style={{ background: bg, color: textColor, minHeight: '400vh', position: 'relative' }}
      initial={{ opacity: 0, y: 50, scale: 0.95 }}
      animate={{ opacity: 1, y: 0, scale: 1 }}
      transition={{ duration: 1.6, ease: [0.16, 1, 0.3, 1] }}
    >
      <div style={{ position: 'fixed', top: 40, left: 48, zIndex: 100 }}>
        <Link href="/" style={{ color: 'inherit', textDecoration: 'none', display: 'flex', alignItems: 'center', gap: 12, fontWeight: 700, fontSize: 12, textTransform: 'uppercase', letterSpacing: '0.2em' }}>
          <ArrowLeft size={16} /> The Broad Sheet
        </Link>
      </div>

      <div style={{ position: 'sticky', top: 0, height: '100vh', display: 'flex', alignItems: 'center', justifyContent: 'center', overflow: 'hidden' }}>
        
        {/* Block 1 */}
        <motion.div style={{ position: 'absolute', y: y1, opacity: o1, filter: blur1, WebkitFilter: blur1, textAlign: 'center', maxWidth: 1000, padding: 40 }}>
          <div style={{ fontSize: 12, letterSpacing: '0.3em', textTransform: 'uppercase', fontWeight: 800, marginBottom: 32, opacity: 0.6 }}>
            Prologue
          </div>
          <h1 className="font-serif" style={{ fontSize: 'clamp(50px, 8vw, 120px)', fontWeight: 900, lineHeight: 0.9, letterSpacing: '-0.04em' }}>
            We watched a generation build <br />
            <span style={{ fontStyle: 'italic', opacity: 0.8 }}>perfect products for empty rooms.</span>
          </h1>
        </motion.div>

        {/* Block 2 */}
        <motion.div style={{ position: 'absolute', y: y2, opacity: o2, filter: blur2, WebkitFilter: blur2, textAlign: 'center', maxWidth: 800, padding: 40 }}>
          <div style={{ fontSize: 12, letterSpacing: '0.3em', textTransform: 'uppercase', fontWeight: 800, marginBottom: 32, opacity: 0.6 }}>
            The Realization
          </div>
          <h2 className="font-serif" style={{ fontSize: 'clamp(40px, 6vw, 90px)', fontWeight: 900, lineHeight: 1, letterSpacing: '-0.03em' }}>
            The code wasn't the risk. <br />
            <motion.span style={{ fontStyle: 'italic', color: accentColor }}>The desire was.</motion.span>
          </h2>
          <p style={{ fontSize: 20, marginTop: 40, fontWeight: 500, lineHeight: 1.6, opacity: 0.7 }}>
            Founders were spending six months to learn what the market knew in two seconds. We needed a way to accelerate the rejection, or amplify the signal.
          </p>
        </motion.div>

        {/* Block 3 */}
        <motion.div style={{ position: 'absolute', y: y3, opacity: o3, filter: blur3, WebkitFilter: blur3, textAlign: 'center', maxWidth: 900, padding: 40 }}>
          <div style={{ fontSize: 12, letterSpacing: '0.3em', textTransform: 'uppercase', fontWeight: 800, marginBottom: 32, opacity: 0.6 }}>
            The Engine
          </div>
          <h2 className="font-serif" style={{ fontSize: 'clamp(50px, 8vw, 110px)', fontWeight: 900, lineHeight: 0.9, letterSpacing: '-0.04em' }}>
            A simulation engine, <br />
            <span style={{ fontStyle: 'italic' }}>filed quarterly.</span>
          </h2>
          <p style={{ fontSize: 22, marginTop: 40, fontWeight: 500, lineHeight: 1.6, opacity: 0.8 }}>
            TheCee wraps 10,000 synthetic readers and 21 domain architects into the familiar, urgent form of a broadsheet. Because the truth about your idea shouldn't take a quarter to read.
          </p>
        </motion.div>

      </div>
      
      {/* Decorative background noise */}
      <div style={{ position: 'fixed', inset: 0, opacity: 0.2, backgroundImage: 'radial-gradient(currentColor 1px, transparent 1px)', backgroundSize: '40px 40px', pointerEvents: 'none', mixBlendMode: 'overlay' }} />
    </motion.main>
  )
}
