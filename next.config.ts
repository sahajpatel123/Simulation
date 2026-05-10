import type { NextConfig } from 'next'

const isProduction = process.env.NODE_ENV === 'production'

// Derive the API origin so local dev (http://localhost:8000) is allowed in
// frame-src alongside the production HTTPS wildcard.  In prod both app and
// API are HTTPS so https: already covers it, but including the origin
// explicitly is harmless and keeps dev and prod parity.
const apiOrigin = (() => {
  const raw = process.env.NEXT_PUBLIC_API_URL ?? 'http://localhost:8000/api/v1'
  try {
    const url = new URL(raw.startsWith('http') ? raw : `https://${raw}`)
    return url.origin
  } catch {
    return 'http://localhost:8000'
  }
})()

const contentSecurityPolicy = [
  "default-src 'self'",
  "base-uri 'self'",
  "frame-ancestors 'none'",
  "img-src 'self' data: blob: https:",
  "font-src 'self' https://fonts.gstatic.com data:",
  "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com",
  "script-src 'self' 'unsafe-inline' 'unsafe-eval'",
  "connect-src 'self' https: wss:",
  "worker-src 'self' blob:",
  // Include the API origin so generated-UI preview iframes (/serve endpoint)
  // are allowed regardless of whether the API is on HTTP (dev) or HTTPS (prod).
  `frame-src 'self' https: ${apiOrigin}`,
  "object-src 'none'",
  "form-action 'self'",
  'upgrade-insecure-requests',
].join('; ')

// Use .nosync suffix locally so iCloud Drive skips syncing build output.
// Without it, iCloud evicts Turbopack chunks between writes and reads,
// causing intermittent 404 errors on page routes during local development.
// On Vercel (process.env.VERCEL is set by the platform) we use the default
// .next directory so Vercel's output serving works correctly.
const nextConfig: NextConfig = {
  distDir: process.env.VERCEL ? '.next' : '.next.nosync',
  async redirects() {
    return [
      {
        source: '/projects/:id/results',
        destination: '/project/:id/results',
        permanent: false,
      },
      {
        source: '/projects/:id/ui-builder',
        destination: '/project/:id/ui-builder',
        permanent: false,
      },
    ]
  },
  async headers() {
    return [
      {
        source: '/(.*)',
        headers: [
          { key: 'Content-Security-Policy', value: contentSecurityPolicy.replace(/\s{2,}/g, ' ').trim() },
          { key: 'Referrer-Policy', value: 'strict-origin-when-cross-origin' },
          { key: 'X-Content-Type-Options', value: 'nosniff' },
          { key: 'X-Frame-Options', value: 'DENY' },
          { key: 'Permissions-Policy', value: 'camera=(), microphone=(), geolocation=()' },
          ...(isProduction
            ? [{ key: 'Strict-Transport-Security', value: 'max-age=31536000; includeSubDomains; preload' }]
            : []),
        ],
      },
    ]
  },
}

export default nextConfig
