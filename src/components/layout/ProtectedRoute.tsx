'use client'

import { useEffect, ReactNode } from 'react'
import { useRouter } from 'next/navigation'
import { auth } from '@/lib/auth'
import { useAuthStore } from '@/store/auth.store'

interface Props {
  children: ReactNode
}

export default function ProtectedRoute({ children }: Props) {
  const router     = useRouter()
  const hydrate    = useAuthStore(s => s.hydrate)
  const isHydrated = useAuthStore(s => s.isHydrated)

  useEffect(() => {
    hydrate()
  }, [hydrate])

  useEffect(() => {
    if (isHydrated && !auth.isAuthenticated()) {
      router.replace('/login')
    }
  }, [isHydrated, router])

  if (!isHydrated) {
    /* Avoid flash of wrong content during localStorage read */
    return (
      <div style={{
        minHeight: '100vh',
        display:   'flex',
        alignItems: 'center',
        justifyContent: 'center',
        background: '#080810',
      }}>
        <div style={{ fontSize: 11, fontFamily: 'system-ui', color: 'rgba(255,255,255,.2)', letterSpacing: '.14em', textTransform: 'uppercase' }}>
          Loading...
        </div>
      </div>
    )
  }

  if (!auth.isAuthenticated()) {
    return null   /* router.replace is in flight */
  }

  return <>{children}</>
}
