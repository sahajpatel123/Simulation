import type { ReactNode } from 'react'

import ProtectedRoute from '@/components/layout/ProtectedRoute'

export default function OnboardingLayout({ children }: { children: ReactNode }) {
  return (
    <ProtectedRoute>
      <div
        className="editorial-workspace paper-grain paper-vignette"
        style={{
          minHeight: '100dvh',
          background: 'var(--paper)',
          color: 'var(--ink)',
          position: 'relative',
        }}
      >
        {children}
      </div>
    </ProtectedRoute>
  )
}
