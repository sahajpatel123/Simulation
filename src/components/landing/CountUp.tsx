'use client'

import { useEffect, useRef, useState } from 'react'

/**
 * Numeric count-up that starts when it scrolls into view.
 * Uses IntersectionObserver (not Motion's useInView) so behaviour is identical
 * in dev and production and does not depend on Motion ref timing.
 */
export default function CountUp({
  to,
  duration = 1400,
  suffix = '',
  decimals = 0,
  className,
  style,
}: {
  to: number
  duration?: number
  suffix?: string
  decimals?: number
  className?: string
  style?: React.CSSProperties
}) {
  const ref = useRef<HTMLSpanElement>(null)
  const [inView, setInView] = useState(false)
  const [value, setValue] = useState(0)

  useEffect(() => {
    const el = ref.current
    if (!el) return

    const io = new IntersectionObserver(
      ([e]) => {
        if (e?.isIntersecting) setInView(true)
      },
      { root: null, rootMargin: '-20% 0px -20% 0px', threshold: 0.01 }
    )
    io.observe(el)
    return () => io.disconnect()
  }, [])

  useEffect(() => {
    if (!inView) return

    const reduce =
      typeof window !== 'undefined' &&
      window.matchMedia?.('(prefers-reduced-motion: reduce)').matches

    if (reduce) {
      setValue(to)
      return
    }

    let raf = 0
    const start = performance.now()
    const ease = (t: number) => 1 - Math.pow(1 - t, 3)

    const tick = (now: number) => {
      const t = Math.min(1, (now - start) / duration)
      setValue(to * ease(t))
      if (t < 1) raf = requestAnimationFrame(tick)
    }
    raf = requestAnimationFrame(tick)
    return () => cancelAnimationFrame(raf)
  }, [inView, to, duration])

  const formatted = decimals
    ? value.toFixed(decimals)
    : Math.round(value).toLocaleString()

  return (
    <span ref={ref} className={className} style={style}>
      {formatted}
      {suffix}
    </span>
  )
}
