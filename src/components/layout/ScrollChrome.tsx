'use client'

import { useEffect } from 'react'

const REVEAL_CLASS = 'thecee-scroll-reveal'
const HIDE_AFTER_MS = 1200

/**
 * Reveals the custom document scrollbar while the user scrolls (wheel / trackpad / touch),
 * then fades it back to invisible — macOS-style, editorial palette, site-wide.
 */
export default function ScrollChrome() {
  useEffect(() => {
    const html = document.documentElement
    const body = document.body
    let hideTimer: ReturnType<typeof setTimeout> | null = null

    const reveal = () => {
      html.classList.add(REVEAL_CLASS)
      body.classList.add(REVEAL_CLASS)
      if (hideTimer) clearTimeout(hideTimer)
      hideTimer = setTimeout(() => {
        html.classList.remove(REVEAL_CLASS)
        body.classList.remove(REVEAL_CLASS)
        hideTimer = null
      }, HIDE_AFTER_MS)
    }

    /* `scroll` covers trackpad, touch momentum, and scrollbar drags. */
    window.addEventListener('scroll', reveal, { passive: true })
    /* `wheel` fires even when the page is at the end of the range (no scroll event). */
    window.addEventListener('wheel', reveal, { passive: true })

    return () => {
      window.removeEventListener('scroll', reveal)
      window.removeEventListener('wheel', reveal)
      if (hideTimer) clearTimeout(hideTimer)
      html.classList.remove(REVEAL_CLASS)
      body.classList.remove(REVEAL_CLASS)
    }
  }, [])

  return null
}
