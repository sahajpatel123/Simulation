import type { NextConfig } from 'next'

// Use .nosync suffix locally so iCloud Drive skips syncing build output.
// Without it, iCloud evicts Turbopack chunks between writes and reads,
// causing intermittent 404 errors on page routes during local development.
// On Vercel (process.env.VERCEL is set by the platform) we use the default
// .next directory so Vercel's output serving works correctly.
const nextConfig: NextConfig = {
  distDir: process.env.VERCEL ? '.next' : '.next.nosync',
}

export default nextConfig
