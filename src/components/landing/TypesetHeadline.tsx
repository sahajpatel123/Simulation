'use client'

import { motion } from 'framer-motion'
import type { CSSProperties } from 'react'

/**
 * Letterpress headline. Each character drops into place with a tiny
 * stagger as if a typesetter is laying metal type into a forme.
 *
 * Pass words[] — each word renders inline; whitespace is preserved.
 * `accentIndex` italicises that word in red.
 */
export default function TypesetHeadline({
  words,
  accentIndex,
  style,
  className = 'font-serif',
  delay = 0,
}: {
  words: string[]
  accentIndex?: number
  style?: CSSProperties
  className?: string
  delay?: number
}) {
  let charIdx = 0
  return (
    <h1
      className={className}
      style={{
        fontWeight: 900,
        letterSpacing: '-0.035em',
        lineHeight: 0.95,
        color: 'var(--ink)',
        margin: 0,
        ...style,
      }}
    >
      {words.map((w, wi) => {
        const isAccent = wi === accentIndex
        return (
          <span key={wi} style={{ display: 'inline-block', whiteSpace: 'pre', marginRight: '0.22em' }}>
            {[...w].map(ch => {
              const i = charIdx++
              return (
                <motion.span
                  key={i}
                  initial={{ y: '0.55em', opacity: 0, filter: 'blur(2px)' }}
                  animate={{ y: 0, opacity: 1, filter: 'blur(0px)' }}
                  transition={{
                    duration: 0.55,
                    delay: delay + i * 0.022,
                    ease: [0.2, 0.7, 0.2, 1],
                  }}
                  style={{
                    display: 'inline-block',
                    color: isAccent ? 'var(--red)' : 'inherit',
                    fontStyle: isAccent ? 'italic' : 'normal',
                  }}
                >
                  {ch}
                </motion.span>
              )
            })}
          </span>
        )
      })}
    </h1>
  )
}
