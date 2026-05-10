'use client'

import React, { useCallback, useEffect, useRef, useState } from 'react'

interface EditorialExpandableProps {
  text: string
  maxWords?: number
  className?: string
}

/** Seconds — matched to transitionend + fallback */
const HEIGHT_DURATION_S = 0.58
/** Smooth ease-out */
const HEIGHT_EASE = 'cubic-bezier(0.22, 1, 0.04, 1)'

const dashSpanStyle: React.CSSProperties = {
  display: 'inline-block',
  width: '0.45em',
  height: '0.06em',
  backgroundColor: '#c0392b',
  borderRadius: '2px',
  cursor: 'pointer',
  userSelect: 'none',
  marginLeft: '0.1em',
  marginBottom: '0.12em',
  verticalAlign: 'middle',
  transformOrigin: 'left center',
}

function usePrefersReducedMotion(): boolean {
  const [reduced, setReduced] = useState(false)
  useEffect(() => {
    const mq = window.matchMedia('(prefers-reduced-motion: reduce)')
    setReduced(mq.matches)
    const onChange = () => setReduced(mq.matches)
    mq.addEventListener('change', onChange)
    return () => mq.removeEventListener('change', onChange)
  }, [])
  return reduced
}

export function EditorialExpandable({
  text,
  maxWords = 10,
  className = '',
}: EditorialExpandableProps) {
  const words = text.trim().split(/\s+/)
  const needsTruncation = words.length > maxWords

  const [expanded, setExpanded] = useState(false)
  const [height, setHeight] = useState<string>('auto')
  const [isTransitioning, setIsTransitioning] = useState(false)
  const containerRef = useRef<HTMLSpanElement>(null)
  const measureRef = useRef<HTMLSpanElement>(null)
  const fallbackTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const transitionEndCleanupRef = useRef<(() => void) | null>(null)
  const prefersReducedMotion = usePrefersReducedMotion()

  const visibleText = needsTruncation ? words.slice(0, maxWords).join(' ') : text

  const clearFallback = useCallback(() => {
    if (fallbackTimerRef.current != null) {
      clearTimeout(fallbackTimerRef.current)
      fallbackTimerRef.current = null
    }
  }, [])

  const clearTransitionEnd = useCallback(() => {
    transitionEndCleanupRef.current?.()
    transitionEndCleanupRef.current = null
  }, [])

  /** Optional hook runs before height returns to auto (e.g. collapse: swap to truncated copy). */
  const completeTransition = useCallback(
    (beforeHeightAuto?: () => void) => {
      clearFallback()
      clearTransitionEnd()
      beforeHeightAuto?.()
      setHeight('auto')
      setIsTransitioning(false)
    },
    [clearFallback, clearTransitionEnd, setHeight, setIsTransitioning]
  )

  useEffect(
    () => () => {
      clearFallback()
      clearTransitionEnd()
    },
    [clearFallback, clearTransitionEnd]
  )

  const runExpand = useCallback(() => {
    const el = containerRef.current
    if (!el || isTransitioning || expanded) return

    if (prefersReducedMotion) {
      clearFallback()
      clearTransitionEnd()
      setExpanded(true)
      setHeight('auto')
      setIsTransitioning(false)
      return
    }

    clearFallback()
    clearTransitionEnd()

    const fromHeight = el.scrollHeight
    setHeight(`${fromHeight}px`)
    setIsTransitioning(true)
    setExpanded(true)

    const settle = () => {
      const node = containerRef.current
      if (!node) {
        completeTransition()
        return
      }
      const toHeight = node.scrollHeight
      setHeight(`${toHeight}px`)

      const onEnd = (ev: TransitionEvent) => {
        if (ev.target !== node || ev.propertyName !== 'height') return
        node.removeEventListener('transitionend', onEnd)
        completeTransition()
      }

      node.addEventListener('transitionend', onEnd)
      transitionEndCleanupRef.current = () => {
        node.removeEventListener('transitionend', onEnd)
      }

      fallbackTimerRef.current = setTimeout(() => {
        completeTransition()
      }, HEIGHT_DURATION_S * 1000 + 120)
    }

    requestAnimationFrame(() => {
      requestAnimationFrame(settle)
    })
  }, [
    clearFallback,
    clearTransitionEnd,
    completeTransition,
    expanded,
    isTransitioning,
    prefersReducedMotion,
    setExpanded,
    setHeight,
    setIsTransitioning,
  ])

  /**
   * Collapse: keep full title + control visible while height animates down (overflow clips excess).
   * Only then set expanded=false so layout and copy stay in sync — avoids “text jumps, page follows later”.
   */
  const runCollapse = useCallback(() => {
    const el = containerRef.current
    const measureEl = measureRef.current
    if (!el || isTransitioning || !expanded) return

    if (prefersReducedMotion) {
      clearFallback()
      clearTransitionEnd()
      setExpanded(false)
      setHeight('auto')
      setIsTransitioning(false)
      return
    }

    clearFallback()
    clearTransitionEnd()

    const fromHeight = el.scrollHeight
    const collapsedH = measureEl?.offsetHeight ?? 0
    const targetH = collapsedH > 0 ? collapsedH : Math.min(fromHeight, fromHeight * 0.45)

    setHeight(`${fromHeight}px`)
    setIsTransitioning(true)
    /* expanded stays true until transition completes */

    const settle = () => {
      const node = containerRef.current
      if (!node) {
        completeTransition(() => setExpanded(false))
        return
      }
      setHeight(`${targetH}px`)

      const onEnd = (ev: TransitionEvent) => {
        if (ev.target !== node || ev.propertyName !== 'height') return
        node.removeEventListener('transitionend', onEnd)
        completeTransition(() => setExpanded(false))
      }

      node.addEventListener('transitionend', onEnd)
      transitionEndCleanupRef.current = () => {
        node.removeEventListener('transitionend', onEnd)
      }

      fallbackTimerRef.current = setTimeout(() => {
        completeTransition(() => setExpanded(false))
      }, HEIGHT_DURATION_S * 1000 + 120)
    }

    requestAnimationFrame(() => {
      requestAnimationFrame(settle)
    })
  }, [
    clearFallback,
    clearTransitionEnd,
    completeTransition,
    expanded,
    isTransitioning,
    prefersReducedMotion,
    setExpanded,
    setHeight,
    setIsTransitioning,
  ])

  const handleExpand = useCallback(() => runExpand(), [runExpand])
  const handleCollapse = useCallback(() => runCollapse(), [runCollapse])

  if (!needsTruncation) {
    return <span className={className}>{text}</span>
  }

  const dashTransition =
    'transform 0.45s cubic-bezier(0.22, 1, 0.04, 1), opacity 0.35s ease, background-color 0.25s ease'

  return (
    <span style={{ position: 'relative', display: 'block' }}>
      {/* In-flow copy: width source for the hidden measurer */}
      <span
        ref={containerRef}
        className={className}
        style={{
          display: 'block',
          overflow: 'hidden',
          height,
          transition: isTransitioning ? `height ${HEIGHT_DURATION_S}s ${HEIGHT_EASE}` : 'none',
          willChange: isTransitioning ? 'height' : undefined,
          paddingBottom: '0.25em',
          marginBottom: '-0.25em',
        }}
      >
        {!expanded ? (
          <>
            {visibleText}
            <span
              onClick={handleExpand}
              role="button"
              aria-label="Read full title"
              tabIndex={0}
              onKeyDown={(e) => {
                if (e.key === 'Enter' || e.key === ' ') {
                  e.preventDefault()
                  handleExpand()
                }
              }}
              style={{
                ...dashSpanStyle,
                transition: dashTransition,
              }}
              onMouseEnter={(e) => {
                e.currentTarget.style.opacity = '0.92'
                e.currentTarget.style.transform = 'scaleX(1.08) scaleY(1.25)'
              }}
              onMouseLeave={(e) => {
                e.currentTarget.style.opacity = '1'
                e.currentTarget.style.transform = 'scaleX(1) scaleY(1)'
              }}
            />
          </>
        ) : (
          <>
            {text}
            <span
              onClick={handleCollapse}
              role="button"
              aria-label="Collapse title"
              tabIndex={0}
              onKeyDown={(e) => {
                if (e.key === 'Enter' || e.key === ' ') {
                  e.preventDefault()
                  handleCollapse()
                }
              }}
              style={{
                color: '#c0392b',
                cursor: 'pointer',
                userSelect: 'none',
                marginLeft: '0.15em',
                fontSize: '0.75em',
                verticalAlign: 'middle',
                lineHeight: 1,
                display: 'inline-block',
                transition: 'opacity 0.4s ease, transform 0.5s cubic-bezier(0.22, 1, 0.04, 1)',
              }}
              onMouseEnter={(e) => {
                e.currentTarget.style.opacity = '0.85'
                e.currentTarget.style.transform = 'translateY(-1px)'
              }}
              onMouseLeave={(e) => {
                e.currentTarget.style.opacity = '1'
                e.currentTarget.style.transform = 'translateY(0)'
              }}
            >
              ↑
            </span>
          </>
        )}
      </span>

      {/* Hidden: same width & type as masthead — target height for collapse (truncated + dash) */}
      <span
        ref={measureRef}
        aria-hidden
        className={className}
        style={{
          position: 'absolute',
          left: 0,
          right: 0,
          top: 0,
          visibility: 'hidden',
          pointerEvents: 'none',
          display: 'block',
          overflow: 'hidden',
          height: 'auto',
          paddingBottom: '0.25em',
          marginBottom: '-0.25em',
        }}
      >
        {visibleText}
        <span style={{ ...dashSpanStyle, cursor: 'default' }} />
      </span>
    </span>
  )
}
