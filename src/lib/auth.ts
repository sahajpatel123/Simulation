/*
  Central token management utility.

  Design decisions:
  - localStorage for JWT storage (standard for SPAs with
    same-origin API — acceptable for MVP)
  - No cookies to avoid CSRF complexity in a React SPA
  - Exported as a plain object (not a hook) so it can be
    called outside React components (axios interceptors,
    middleware, server actions)
  - Token expiry decoding is lightweight — no jwt-decode
    dependency, just base64 parsing
*/

const ACCESS_KEY  = 'access_token'
const REFRESH_KEY = 'refresh_token'
const USER_KEY    = 'thecee_user'

function decodePayload(token: string): Record<string, unknown> | null {
  try {
    const base64 = token.split('.')[1]
    if (!base64) return null
    const normalized = base64.replace(/-/g, '+').replace(/_/g, '/')
    const pad = normalized.length % 4 === 0 ? '' : '='.repeat(4 - (normalized.length % 4))
    const json = atob(normalized + pad)
    return JSON.parse(json)
  } catch {
    return null
  }
}

export const auth = {
  setTokens(accessToken: string, refreshToken?: string): void {
    if (typeof window === 'undefined') return
    localStorage.setItem(ACCESS_KEY, accessToken)
    if (refreshToken) localStorage.setItem(REFRESH_KEY, refreshToken)
  },

  getToken(): string | null {
    if (typeof window === 'undefined') return null
    return localStorage.getItem(ACCESS_KEY)
  },

  getRefreshToken(): string | null {
    if (typeof window === 'undefined') return null
    return localStorage.getItem(REFRESH_KEY)
  },

  clearTokens(): void {
    if (typeof window === 'undefined') return
    localStorage.removeItem(ACCESS_KEY)
    localStorage.removeItem(REFRESH_KEY)
    localStorage.removeItem(USER_KEY)
  },

  isAuthenticated(): boolean {
    const token = this.getToken()
    if (!token) return false
    /* Check expiry from JWT payload — avoids unnecessary API calls */
    const payload = decodePayload(token)
    if (!payload || typeof payload.exp !== 'number') return true
    /* Give a 30-second buffer to account for clock skew */
    return payload.exp > Math.floor(Date.now() / 1000) + 30
  },

  /* Persist user profile so we don't re-fetch on every page */
  setUser(user: Record<string, unknown>): void {
    if (typeof window === 'undefined') return
    localStorage.setItem(USER_KEY, JSON.stringify(user))
  },

  getUser(): Record<string, unknown> | null {
    if (typeof window === 'undefined') return null
    try {
      const raw = localStorage.getItem(USER_KEY)
      return raw ? JSON.parse(raw) : null
    } catch {
      return null
    }
  },
}
