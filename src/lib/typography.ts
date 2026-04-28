export function editorialTruncate(text: string, maxWords: number = 10): string {
  const words = text.trim().split(/\s+/)
  if (words.length <= maxWords) return text
  return words.slice(0, maxWords).join(' ') + '\u2014'
}
