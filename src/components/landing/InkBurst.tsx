'use client'

import { forwardRef, useImperativeHandle, useRef } from 'react'

export type InkBurstHandle = {
  /** Trigger an ink explosion from a viewport-relative origin (px). */
  burst: (x: number, y: number, onPeak?: () => void) => void
}

type Particle = {
  x: number
  y: number
  vx: number
  vy: number
  r: number
  life: number
  maxLife: number
  ink: number // 0..1 ink density, fades
}

/**
 * Full-screen canvas that paints a violent red-ink eruption from a point.
 * Used as the CTA transition — the press goes off, ink covers the page,
 * then drains away to reveal the next world.
 *
 * Imperative API via ref.
 */
const InkBurst = forwardRef<InkBurstHandle>(function InkBurst(_, ref) {
  const canvasRef = useRef<HTMLCanvasElement>(null)
  const rafRef = useRef<number>(0)

  useImperativeHandle(ref, () => ({
    burst(x, y, onPeak) {
      const canvas = canvasRef.current
      if (!canvas) return
      const ctx = canvas.getContext('2d')
      if (!ctx) return

      const dpr = Math.min(window.devicePixelRatio || 1, 2)
      canvas.width = window.innerWidth * dpr
      canvas.height = window.innerHeight * dpr
      canvas.style.width = window.innerWidth + 'px'
      canvas.style.height = window.innerHeight + 'px'
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0)

      const particles: Particle[] = []
      const COUNT = 280
      const maxR = Math.max(window.innerWidth, window.innerHeight)

      for (let i = 0; i < COUNT; i++) {
        const angle = Math.random() * Math.PI * 2
        const speed = 8 + Math.random() * 36
        particles.push({
          x,
          y,
          vx: Math.cos(angle) * speed,
          vy: Math.sin(angle) * speed,
          r: 6 + Math.random() * 28,
          life: 0,
          maxLife: 90 + Math.random() * 70,
          ink: 0.6 + Math.random() * 0.4,
        })
      }

      let frame = 0
      let peakSent = false
      const tick = () => {
        // Slight motion blur — fade existing pixels rather than wipe.
        ctx.fillStyle = 'rgba(242,236,224,0.04)'
        ctx.fillRect(0, 0, window.innerWidth, window.innerHeight)

        for (const p of particles) {
          p.life++
          p.x += p.vx
          p.y += p.vy
          p.vx *= 0.96
          p.vy *= 0.96
          p.vy += 0.18 // tiny gravity, ink dripping

          const t = 1 - p.life / p.maxLife
          if (t <= 0) continue
          const alpha = Math.max(0, p.ink * t * t)
          ctx.beginPath()
          ctx.arc(p.x, p.y, p.r * (0.6 + t * 0.8), 0, Math.PI * 2)
          ctx.fillStyle = `rgba(192,57,43,${alpha})`
          ctx.fill()
        }

        // Expanding wash — paints whole screen briefly red.
        if (frame < 30) {
          const washR = (frame / 30) * maxR
          const washA = 0.55 - (frame / 30) * 0.4
          const grad = ctx.createRadialGradient(x, y, 0, x, y, washR)
          grad.addColorStop(0, `rgba(192,57,43,${washA})`)
          grad.addColorStop(1, 'rgba(192,57,43,0)')
          ctx.fillStyle = grad
          ctx.fillRect(0, 0, window.innerWidth, window.innerHeight)
        }

        if (!peakSent && frame >= 24) {
          peakSent = true
          onPeak?.()
        }

        frame++
        if (frame < 200) {
          rafRef.current = requestAnimationFrame(tick)
        } else {
          ctx.clearRect(0, 0, window.innerWidth, window.innerHeight)
        }
      }
      cancelAnimationFrame(rafRef.current)
      rafRef.current = requestAnimationFrame(tick)
    },
  }))

  return (
    <canvas
      ref={canvasRef}
      style={{
        position: 'fixed',
        inset: 0,
        pointerEvents: 'none',
        zIndex: 9000,
      }}
      aria-hidden
    />
  )
})

export default InkBurst
