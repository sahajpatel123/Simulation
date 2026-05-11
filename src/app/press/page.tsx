'use client'

import React, { useRef } from 'react'
import { motion, useScroll, useTransform, useSpring, type Variants } from 'framer-motion'
import Link from 'next/link'
import { ArrowLeft } from 'lucide-react'

export default function PressPage() {
  const ref = useRef(null)
  const { scrollYProgress } = useScroll({ target: ref, offset: ['start start', 'end end'] })
  const smooth = useSpring(scrollYProgress, { stiffness: 50, damping: 20 })

  // Ticker tapes moving in opposite directions
  const x1 = useTransform(smooth, [0, 1], ['0%', '-50%'])
  const x2 = useTransform(smooth, [0, 1], ['-50%', '0%'])
  const x3 = useTransform(smooth, [0, 1], ['0%', '-50%'])

  const headlines = [
    "THECEE LAUNCHES BEHAVIORAL ENGINE",
    "END OF THE A/B TEST",
    "STARTUPS NOW SIMULATED BEFORE INCORPORATION",
    "MARKOV FUNNELS REPLACE MVP",
    "FOUNDERS SAVE MILLIONS IN ENGINEERING COSTS",
    "THE DEATH OF 'BUILD AND THEY WILL COME'",
    "10,000 SYNTHETIC READERS CAN'T BE WRONG",
    "THECEE LAUNCHES BEHAVIORAL ENGINE",
    "END OF THE A/B TEST",
  ]

  const variants: Variants = {
    hidden: { opacity: 0, filter: 'blur(10px)', y: 20 },
    visible: (i: number) => ({
      opacity: 1,
      filter: 'blur(0px)',
      y: 0,
      transition: { delay: i * 0.1, duration: 1, ease: [0.16, 1, 0.3, 1] }
    })
  }

  return (
    <motion.main ref={ref} style={{ background: '#0a0a0a', color: 'var(--paper)', minHeight: '200vh', position: 'relative' }}
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      transition={{ duration: 1.5 }}
    >
      <div style={{ position: 'fixed', top: 40, left: 48, zIndex: 100 }}>
        <Link href="/" style={{ color: 'var(--paper)', textDecoration: 'none', display: 'flex', alignItems: 'center', gap: 12, fontWeight: 700, fontSize: 12, textTransform: 'uppercase', letterSpacing: '0.2em' }}>
          <ArrowLeft size={16} /> Press & Media
        </Link>
      </div>

      <div style={{ position: 'sticky', top: 0, height: '100vh', display: 'flex', flexDirection: 'column', justifyContent: 'center', overflow: 'hidden' }}>
        
        <div style={{ marginBottom: 100, padding: '0 10vw' }}>
          <motion.div initial="hidden" animate="visible" custom={0} variants={variants} style={{ fontSize: 12, letterSpacing: '0.3em', textTransform: 'uppercase', color: 'var(--red)', fontWeight: 800, marginBottom: 24 }}>
            In the News
          </motion.div>
          <motion.h1 initial="hidden" animate="visible" custom={1} variants={variants} className="font-serif" style={{ fontSize: 'clamp(50px, 8vw, 120px)', fontWeight: 900, lineHeight: 0.9, letterSpacing: '-0.04em', margin: 0 }}>
            The headlines <br />
            <span style={{ fontStyle: 'italic', color: 'rgba(255,255,255,0.6)' }}>we didn't write.</span>
          </motion.h1>
        </div>

        {/* Ticker 1 */}
        <div style={{ width: '200vw', display: 'flex', whiteSpace: 'nowrap', overflow: 'hidden', padding: '20px 0', borderTop: '1px solid rgba(255,255,255,0.1)' }}>
          <motion.div style={{ x: x1, display: 'flex', gap: 60, fontSize: 48, fontWeight: 900, fontFamily: 'var(--font-serif)', letterSpacing: '-0.02em', textTransform: 'uppercase' }}>
            {headlines.map((h, i) => <span key={`t1-${i}`}>{h}</span>)}
          </motion.div>
        </div>

        {/* Ticker 2 */}
        <div style={{ width: '200vw', display: 'flex', whiteSpace: 'nowrap', overflow: 'hidden', padding: '20px 0', borderTop: '1px solid rgba(255,255,255,0.1)', color: 'var(--red)' }}>
          <motion.div style={{ x: x2, display: 'flex', gap: 60, fontSize: 48, fontWeight: 900, fontFamily: 'var(--font-serif)', letterSpacing: '-0.02em', textTransform: 'uppercase', fontStyle: 'italic' }}>
            {headlines.map((h, i) => <span key={`t2-${i}`}>{h}</span>)}
          </motion.div>
        </div>

        {/* Ticker 3 */}
        <div style={{ width: '200vw', display: 'flex', whiteSpace: 'nowrap', overflow: 'hidden', padding: '20px 0', borderTop: '1px solid rgba(255,255,255,0.1)', borderBottom: '1px solid rgba(255,255,255,0.1)', color: 'rgba(255,255,255,0.3)' }}>
          <motion.div style={{ x: x3, display: 'flex', gap: 60, fontSize: 48, fontWeight: 900, fontFamily: 'var(--font-serif)', letterSpacing: '-0.02em', textTransform: 'uppercase' }}>
            {headlines.map((h, i) => <span key={`t3-${i}`}>{h}</span>)}
          </motion.div>
        </div>

      </div>
    </motion.main>
  )
}
