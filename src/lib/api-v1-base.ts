/**
 * Matches `src/lib/api.ts`: env may be origin-only or already include `/api/v1`.
 */
export function getApiV1Base(): string {
  const raw = (process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000/api/v1').replace(/\/$/, '')
  if (/\/api\/v1\/?$/.test(raw)) return raw
  return `${raw}/api/v1`
}

export function getApiOriginFromV1Base(apiV1: string): string {
  return apiV1.replace(/\/api\/v1$/, '') || apiV1
}
