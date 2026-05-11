'use client'

import React, { useRef } from 'react'
import { motion, useScroll, useTransform, useSpring } from 'framer-motion'
import Link from 'next/link'
import { ArrowLeft, Target, GitMerge, Activity } from 'lucide-react'

export default function MethodologyPage() {
  const ref = useRef(null)
  const { scrollYProgress } = useScroll({ target: ref, offset: ['start start', 'end end'] })
  
  // Smooth out the scroll for the grid
  const smoothProgress = useSpring(scrollYProgress, { stiffness: 100, damping: 30 })

  // Animate the main diagram
  const scale = useTransform(smoothProgress, [0, 1], [0.8, 1.2])
  const rotateX = useTransform(smoothProgress, [0, 1], [45, 0])
  const opacity = useTransform(smoothProgress, [0, 0.2], [0, 1])

  return (
    <motion.main ref={ref} style={{ background: '#f4f3ef', minHeight: '200vh', position: 'relative', perspective: 1000 }}
      initial={{ opacity: 0, filter: 'grayscale(100%)' }}
      animate={{ opacity: 1, filter: 'grayscale(0%)' }}
      transition={{ duration: 2, ease: "anticipate" }}
    >
      <div style={{ position: 'fixed', top: 40, left: 48, zIndex: 100 }}>
        <Link href="/" style={{ color: 'var(--ink)', textDecoration: 'none', display: 'flex', alignItems: 'center', gap: 12, fontWeight: 700, fontSize: 12, textTransform: 'uppercase', letterSpacing: '0.2em' }}>
          <ArrowLeft size={16} /> Return
        </Link>
      </div>

      <div style={{ position: 'sticky', top: 0, height: '100vh', display: 'flex', alignItems: 'center', justifyContent: 'center', overflow: 'hidden' }}>
        
        {/* Left Text */}
        <div style={{ position: 'absolute', left: '10%', top: '50%', transform: 'translateY(-50%)', maxWidth: 400, zIndex: 10 }}>
          <motion.div style={{ opacity: useTransform(smoothProgress, [0, 0.3], [1, 0]), y: useTransform(smoothProgress, [0, 0.3], [0, -50]) }}>
            <h1 className="font-serif" style={{ fontSize: 64, fontWeight: 900, lineHeight: 0.9, letterSpacing: '-0.04em', color: 'var(--ink)', marginBottom: 24 }}>
              The <br /><span style={{ fontStyle: 'italic', color: 'var(--red)' }}>Methodology.</span>
            </h1>
            <p style={{ fontSize: 18, color: 'var(--ink-secondary)', lineHeight: 1.6, fontWeight: 500 }}>
              We do not ask people if they like your idea. We construct 52 deterministic behavioral clusters and force them to make a buying decision.
            </p>
          </motion.div>

          <motion.div style={{ opacity: useTransform(smoothProgress, [0.3, 0.6], [0, 1]), y: useTransform(smoothProgress, [0.3, 0.6], [50, 0]), position: 'absolute', top: 0 }}>
            <h2 className="font-serif" style={{ fontSize: 48, fontWeight: 900, lineHeight: 0.9, letterSpacing: '-0.03em', color: 'var(--ink)', marginBottom: 24 }}>
              21 Domain <br /><span style={{ fontStyle: 'italic' }}>Architects.</span>
            </h2>
            <p style={{ fontSize: 18, color: 'var(--ink-secondary)', lineHeight: 1.6, fontWeight: 500 }}>
              Each idea is scrutinized across pricing, trust, channels, and timing. The matrices mutate based on their adversarial evaluations.
            </p>
          </motion.div>
        </div>

        {/* 3D Grid Visualization */}
        <motion.div style={{ 
          scale, rotateX, opacity,
          display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 16,
          width: 600, height: 600, marginLeft: '30%',
          transformStyle: 'preserve-3d'
        }}>
          {Array.from({ length: 16 }).map((_, i) => (
            <motion.div 
              key={i}
              style={{
                background: 'var(--paper)',
                border: '1px solid rgba(26,23,20,0.1)',
                borderRadius: 16,
                boxShadow: '0 10px 30px rgba(0,0,0,0.05)',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                color: 'var(--ink)',
                y: useTransform(smoothProgress, [0, 1], [Math.random() * 200 - 100, 0]),
                rotateY: useTransform(smoothProgress, [0, 1], [Math.random() * 90 - 45, 0]),
                opacity: useTransform(smoothProgress, [0, 0.2 + Math.random() * 0.5], [0, 1])
              }}
            >
              {i % 3 === 0 ? <Target size={32} color="var(--red)" opacity={0.5} /> : 
               i % 3 === 1 ? <GitMerge size={32} opacity={0.2} /> : 
               <Activity size={32} opacity={0.2} />}
            </motion.div>
          ))}
        </motion.div>

      </div>
      
      {/* Blueprint Grid Background */}
      <div style={{ position: 'fixed', inset: 0, opacity: 0.3, backgroundImage: 'linear-gradient(rgba(26,23,20,0.1) 1px, transparent 1px), linear-gradient(90deg, rgba(26,23,20,0.1) 1px, transparent 1px)', backgroundSize: '100px 100px', pointerEvents: 'none' }} />
    </motion.main>
  )
}
