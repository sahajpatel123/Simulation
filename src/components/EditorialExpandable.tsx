'use client'

import React, { useCallback, useEffect, useRef, useState } from 'react'

interface EditorialExpandableProps {
  text: string
  maxWords?: number
  className?: string
}

/** Seconds — matched to transitionend + fallback */
const HEIGHT_DURATION_S = 0.58
/** Smooth ease-out (decelerates gently at the end of expand/collapse) */
const HEIGHT_EASE = 'cubic-bezier(0.22, 1, 0.04, 1)'

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

  const finishHeightTransition = useCallback(() => {
    clearFallback()
    clearTransitionEnd()
    setHeight('auto')
    setIsTransitioning(false)
  }, [clearFallback, clearTransitionEnd])

  useEffect(
    () => () => {
      clearFallback()
      clearTransitionEnd()
    },
    [clearFallback, clearTransitionEnd]
  )

  const runHeightTransition = useCallback(
    (nextExpanded: boolean) => {
      const el = containerRef.current
      if (!el) return

      if (prefersReducedMotion) {
        clearFallback()
        clearTransitionEnd()
        setExpanded(nextExpanded)
        setHeight('auto')
        setIsTransitioning(false)
        return
      }

      clearFallback()
      clearTransitionEnd()

      const fromHeight = el.scrollHeight
      setHeight(`${fromHeight}px`)
      setIsTransitioning(true)
      setExpanded(nextExpanded)

      const settle = () => {
        const node = containerRef.current
        if (!node) {
          finishHeightTransition()
          return
        }
        const toHeight = node.scrollHeight
        setHeight(`${toHeight}px`)

        const onEnd = (ev: TransitionEvent) => {
          if (ev.target !== node || ev.propertyName !== 'height') return
          node.removeEventListener('transitionend', onEnd)
          finishHeightTransition()
        }

        node.addEventListener('transitionend', onEnd)
        transitionEndCleanupRef.current = () => {
          node.removeEventListener('transitionend', onEnd)
        }

        fallbackTimerRef.current = setTimeout(() => {
          finishHeightTransition()
        }, HEIGHT_DURATION_S * 1000 + 120)
      }

      requestAnimationFrame(() => {
        requestAnimationFrame(settle)
      })
    },
    [clearFallback, clearTransitionEnd, finishHeightTransition, prefersReducedMotion]
  )

  const handleExpand = useCallback(() => runHeightTransition(true), [runHeightTransition])
  const handleCollapse = useCallback(() => runHeightTransition(false), [runHeightTransition])

  if (!needsTruncation) {
    return <span className={className}>{text}</span>
  }

  const dashTransition =
    'transform 0.45s cubic-bezier(0.22, 1, 0.04, 1), opacity 0.35s ease, background-color 0.25s ease'

  return (
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
              transition: dashTransition,
              transformOrigin: 'left center',
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
  )
}
