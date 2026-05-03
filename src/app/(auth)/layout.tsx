import type { ReactNode } from 'react'

export default function AuthLayout({ children }: { children: ReactNode }) {
  return (
    <div className="editorial-workspace" style={{ minHeight: '100dvh' }}>
      {children}
    </div>
  )
}
