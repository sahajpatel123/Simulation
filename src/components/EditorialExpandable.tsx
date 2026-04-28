'use client'

import React, { useState, useRef } from 'react'

interface EditorialExpandableProps {
  text: string
  maxWords?: number
  className?: string
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

  const visibleText = needsTruncation ? words.slice(0, maxWords).join(' ') : text

  if (!needsTruncation) {
    return <span className={className}>{text}</span>
  }

  const handleExpand = () => {
    const el = containerRef.current
    if (!el) return

    const fromHeight = el.scrollHeight
    setHeight(`${fromHeight}px`)
    setIsTransitioning(true)
    setExpanded(true)

    requestAnimationFrame(() => {
      requestAnimationFrame(() => {
        if (!containerRef.current) return
        const toHeight = containerRef.current.scrollHeight
        setHeight(`${toHeight}px`)
        setTimeout(() => {
          setHeight('auto')
          setIsTransitioning(false)
        }, 400)
      })
    })
  }

  const handleCollapse = () => {
    const el = containerRef.current
    if (!el) return

    const fromHeight = el.scrollHeight
    setHeight(`${fromHeight}px`)
    setIsTransitioning(true)
    setExpanded(false)

    requestAnimationFrame(() => {
      requestAnimationFrame(() => {
        if (!containerRef.current) return
        const toHeight = containerRef.current.scrollHeight
        setHeight(`${toHeight}px`)
        setTimeout(() => {
          setHeight('auto')
          setIsTransitioning(false)
        }, 400)
      })
    })
  }

  return (
    <span
      ref={containerRef}
      className={className}
      style={{
        display: 'block',
        overflow: 'hidden',
        height,
        transition: isTransitioning
          ? 'height 0.4s cubic-bezier(0.4, 0, 0.2, 1)'
          : 'none',
      }}
    >
      {!expanded ? (
        <>
          {visibleText}
          <span
            onClick={handleExpand}
            role="button"
            aria-label="Read full title"
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
            style={{
              color: '#c0392b',
              cursor: 'pointer',
              userSelect: 'none',
              marginLeft: '0.15em',
              fontSize: '0.75em',
              verticalAlign: 'middle',
              lineHeight: 1,
            }}
          >
            ↑
          </span>
        </>
      )}
    </span>
  )
}
