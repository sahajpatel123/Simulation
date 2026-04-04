import type { NextConfig } from 'next'

const nextConfig: NextConfig = {
  experimental: {
    turbopackMemoryLimit: 512 * 1024 * 1024,
  },
}

export default nextConfig
