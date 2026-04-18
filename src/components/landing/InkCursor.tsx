'use client'

import { useEffect, useRef } from 'react'

/**
 * Ink-bleed cursor trail. A canvas pinned to the viewport that
 * paints faint red dots wherever the cursor moves, then fades them
 * with a slow opacity wash. Subtle — not glittery.
 */
export default function InkCursor() {
  const canvasRef = useRef<HTMLCanvasElement>(null)

  useEffect(() => {
    const canvas = canvasRef.current
    if (!canvas) return
    const ctx = canvas.getContext('2d')
    if (!ctx) return

    const dpr = Math.min(window.devicePixelRatio || 1, 2)
    const resize = () => {
      canvas.width = window.innerWidth * dpr
      canvas.height = window.innerHeight * dpr
      canvas.style.width = window.innerWidth + 'px'
      canvas.style.height = window.innerHeight + 'px'
      ctx.scale(dpr, dpr)
    }
    resize()
    window.addEventListener('resize', resize)

    const dots: { x: number; y: number; r: number; a: number }[] = []
    let last = { x: -100, y: -100 }
    let raf = 0

    const onMove = (e: MouseEvent) => {
      const dx = e.clientX - last.x
      const dy = e.clientY - last.y
      const d = Math.hypot(dx, dy)
      if (d > 4) {
        dots.push({
          x: e.clientX + (Math.random() - 0.5) * 2,
          y: e.clientY + (Math.random() - 0.5) * 2,
          r: 1.2 + Math.random() * 1.4,
          a: 0.18,
        })
        last = { x: e.clientX, y: e.clientY }
      }
    }

    const tick = () => {
      ctx.clearRect(0, 0, canvas.width, canvas.height)
      for (let i = dots.length - 1; i >= 0; i--) {
        const d = dots[i]
        d.a -= 0.006
        if (d.a <= 0) {
          dots.splice(i, 1)
          continue
        }
        ctx.beginPath()
        ctx.arc(d.x, d.y, d.r, 0, Math.PI * 2)
        ctx.fillStyle = `rgba(192,57,43,${d.a})`
        ctx.fill()
      }
      raf = requestAnimationFrame(tick)
    }
    tick()

    window.addEventListener('mousemove', onMove)
    return () => {
      window.removeEventListener('mousemove', onMove)
      window.removeEventListener('resize', resize)
      cancelAnimationFrame(raf)
    }
  }, [])

  return (
    <canvas
      ref={canvasRef}
      style={{
        position: 'fixed',
        inset: 0,
        pointerEvents: 'none',
        zIndex: 200,
        mixBlendMode: 'multiply',
      }}
      aria-hidden
    />
  )
}
