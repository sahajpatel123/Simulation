'use client'

import { useEffect, useState } from 'react'
import { usePathname } from 'next/navigation'

import Sidebar from '@/components/layout/Sidebar'
import ProtectedRoute from '@/components/layout/ProtectedRoute'
import UserMenu from '@/components/layout/UserMenu'

export default function DashboardLayout({ children }: { children: React.ReactNode }) {
  const pathname = usePathname()
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false)

  useEffect(() => {
    if (!pathname) return
    if (pathname.match(/^\/project\/\d+\/prototype\/?$/)) {
      setSidebarCollapsed(true)
    }
    if (pathname.match(/^\/project\/\d+\/hardware\/?$/)) {
      setSidebarCollapsed(true)
    }
  }, [pathname])

  return (
    <ProtectedRoute>
      <div
        id="app-shell"
        className="paper-grain paper-vignette app-shell editorial-workspace"
        style={{
          minHeight: '100dvh',
          background: 'var(--paper)',
          color: 'var(--ink)',
          position: 'relative',
        }}
      >
        {/* ─── MASTHEAD ───────────────────────────────────────── */}
        <header
          style={{
            position: 'sticky',
            top: 0,
            zIndex: 30,
            background: 'var(--paper)',
            borderBottom: '0.5px solid var(--border-strong)',
          }}
        >
          {/* Masthead row */}
          <div
            style={{
              display: 'grid',
              gridTemplateColumns: '1fr auto 1fr',
              alignItems: 'center',
              padding: '18px 40px',
              gap: 24,
            }}
          >
            {/* Left — section indicator */}
            <div style={{ display: 'flex', alignItems: 'center', gap: 14 }}>
              <span
                style={{
                  fontSize: 10,
                  letterSpacing: '0.3em',
                  textTransform: 'uppercase',
                  color: 'var(--ink-secondary)',
                  fontWeight: 500,
                }}
              >
                Workspace
              </span>
              <span
                style={{
                  display: 'inline-block',
                  width: 28,
                  height: 0.5,
                  background: 'var(--ink-secondary)',
                }}
              />
              <span
                style={{
                  fontSize: 10,
                  letterSpacing: '0.3em',
                  textTransform: 'uppercase',
                  color: 'var(--red)',
                  fontWeight: 600,
                }}
              >
                Private Files
              </span>
            </div>

            {/* Centre — wordmark (match landing masthead TheCee) */}
            <a
              href="/projects"
              className="font-serif"
              style={{
                fontSize: 26,
                fontWeight: 900,
                letterSpacing: '-0.04em',
                color: 'var(--ink)',
                textDecoration: 'none',
                lineHeight: 1,
                fontStyle: 'italic',
              }}
            >
              TheCee<span style={{ color: 'var(--red)' }}>.</span>
            </a>

            {/* Right — account */}
            <div style={{ display: 'flex', justifyContent: 'flex-end', alignItems: 'center', gap: 20 }}>
              <span
                style={{
                  fontSize: 10,
                  letterSpacing: '0.22em',
                  textTransform: 'uppercase',
                  color: 'var(--ink-secondary)',
                  fontWeight: 500,
                }}
              >
                Editor&rsquo;s Desk
              </span>
              <UserMenu />
            </div>
          </div>

          {/* Bottom rule (thin red, like a printed masthead) */}
          <div style={{ height: 2, background: 'var(--red)' }} />
        </header>

        {/* ─── BODY: left rail + main ─────────────────────────── */}
        <div
          style={{
            display: 'grid',
            gridTemplateColumns: sidebarCollapsed ? '52px 1fr' : '220px 1fr',
            transition: 'grid-template-columns 280ms cubic-bezier(0.2, 0.75, 0.2, 1)',
            position: 'relative',
            zIndex: 2,
          }}
        >
          <Sidebar
            collapsed={sidebarCollapsed}
            onCollapse={() => setSidebarCollapsed(true)}
            onExpand={() => setSidebarCollapsed(false)}
          />
          <main style={{ minHeight: 'calc(100dvh - 100px)', position: 'relative' }}>{children}</main>
        </div>
      </div>
    </ProtectedRoute>
  )
}
