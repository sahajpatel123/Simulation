import React from 'react'

export function editorialTruncate(text: string, maxWords: number = 10): React.ReactNode {
  const words = text.trim().split(/\s+/)

  if (words.length <= maxWords) return text

  const visible = words.slice(0, maxWords).join(' ')

  return (
    <>
      {visible}
      <span style={{ color: '#c0392b' }} aria-hidden="true">
        {'\u2014'}
      </span>
    </>
  )
}
