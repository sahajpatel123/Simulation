import type { ReactNode } from 'react'

import ProtectedRoute from '@/components/layout/ProtectedRoute'

export default function OnboardingLayout({ children }: { children: ReactNode }) {
  return <ProtectedRoute>{children}</ProtectedRoute>
}
