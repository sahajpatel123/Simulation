'use client'

import { useEffect } from 'react'
import { useAuthStore } from '@/store/auth.store'

export default function HydrateAuth() {
  const hydrate = useAuthStore(s => s.hydrate)
  useEffect(() => { hydrate() }, [hydrate])
  return null
}
