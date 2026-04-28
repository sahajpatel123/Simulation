'use client'

import React, { useState, useRef, useEffect } from 'react'

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
  const [height, setHeight] = useState<number | 'auto'>('auto')
  const [isAnimating, setIsAnimating] = useState(false)
  const contentRef = useRef<HTMLSpanElement>(null)
  const collapsedRef = useRef<HTMLSpanElement>(null)

  const visibleText = needsTruncation ? words.slice(0, maxWords).join(' ') : text

  useEffect(() => {
    if (!needsTruncation) return
    if (!contentRef.current || !collapsedRef.current) return

    if (expanded) {
      const fullHeight = contentRef.current.scrollHeight
      setHeight(fullHeight)
      setIsAnimating(true)
      const timer = setTimeout(() => {
        setHeight('auto')
        setIsAnimating(false)
      }, 400)
      return () => clearTimeout(timer)
    } else {
      if (height === 'auto') {
        const currentHeight = contentRef.current.scrollHeight
        setHeight(currentHeight)
        requestAnimationFrame(() => {
          requestAnimationFrame(() => {
            setHeight(collapsedRef.current?.scrollHeight ?? 'auto')
            setIsAnimating(true)
            const timer = setTimeout(() => {
              setIsAnimating(false)
            }, 400)
          })
        })
      } else {
        setHeight(collapsedRef.current?.scrollHeight ?? 'auto')
        setIsAnimating(true)
        const timer = setTimeout(() => {
          setIsAnimating(false)
        }, 400)
        return () => clearTimeout(timer)
      }
    }
  }, [expanded])

  if (!needsTruncation) {
    return <span className={className}>{text}</span>
  }

  return (
    <span
      ref={contentRef}
      className={className}
      style={{
        display: 'block',
        overflow: 'hidden',
        height: height === 'auto' ? 'auto' : `${height}px`,
        transition: isAnimating ? 'height 0.4s cubic-bezier(0.4, 0, 0.2, 1)' : 'none',
      }}
    >
      <span ref={collapsedRef} style={{ display: 'none' }}>
        {visibleText}
      </span>

      {!expanded ? (
        <>
          {visibleText}
          <span
            onClick={() => setExpanded(true)}
            aria-label="Read full title"
            role="button"
            style={{
              color: '#c0392b',
              cursor: 'pointer',
              userSelect: 'none',
              marginLeft: '0.05em',
            }}
          >
            &#x2014;
          </span>
        </>
      ) : (
        <>
          {text}
          <span
            onClick={() => setExpanded(false)}
            aria-label="Collapse title"
            role="button"
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
