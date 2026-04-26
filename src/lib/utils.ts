import { clsx, type ClassValue } from "clsx"
import { twMerge } from "tailwind-merge"

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs))
}

/** Hard truncate a string at the last word boundary before maxLen and append an ellipsis. */
export function truncateAtWord(text: string, maxLen: number): string {
  if (!text || text.length <= maxLen) return text
  const slice = text.slice(0, maxLen)
  const lastSpace = slice.lastIndexOf(' ')
  const cut = lastSpace > maxLen * 0.6 ? slice.slice(0, lastSpace) : slice
  return cut.replace(/[\s,;:.\-—]+$/, '') + '…'
}
