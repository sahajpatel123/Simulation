'use client'

import { useState } from 'react'
import { useLogout } from '@/hooks/useAuth'
import { useAuthStore } from '@/store/auth.store'

export default function UserMenu() {
  const [open, setOpen] = useState(false)
  const user = useAuthStore(s => s.user)
  const logout = useLogout()

  if (!user) return null

  const initials = (user.full_name || user.email)
    .split(' ')
    .map(w => w[0]?.toUpperCase() ?? '')
    .slice(0, 2)
    .join('')

  return (
    <div style={{ position: 'relative' }}>
      <button
        onClick={() => setOpen(o => !o)}
        aria-label="Account menu"
        style={{
          width: 36,
          height: 36,
          borderRadius: 0,
          background: 'var(--ink)',
          border: '0.5px solid var(--ink)',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          cursor: 'pointer',
          fontSize: 11,
          fontFamily: 'var(--font-body, system-ui, sans-serif)',
          fontWeight: 600,
          color: 'var(--paper)',
          letterSpacing: '0.12em',
          transition: 'background 180ms ease',
        }}
        onMouseEnter={(e) => (e.currentTarget.style.background = 'var(--red)')}
        onMouseLeave={(e) => (e.currentTarget.style.background = 'var(--ink)')}
      >
        {initials}
      </button>

      {open && (
        <>
          <div
            onClick={() => setOpen(false)}
            style={{ position: 'fixed', inset: 0, zIndex: 40 }}
          />
          <div
            style={{
              position: 'absolute',
              top: 44,
              right: 0,
              width: 240,
              background: 'var(--paper)',
              border: '0.5px solid var(--ink)',
              borderRadius: 0,
              padding: 0,
              boxShadow: '12px 12px 0 rgba(26,23,20,0.10)',
              zIndex: 50,
            }}
          >
            <div
              style={{
                padding: '14px 18px 12px',
                borderBottom: '0.5px solid var(--border-color)',
              }}
            >
              <div
                style={{
                  fontSize: 9,
                  letterSpacing: '0.3em',
                  textTransform: 'uppercase',
                  color: 'var(--red)',
                  fontWeight: 600,
                  marginBottom: 6,
                }}
              >
                Subscriber
              </div>
              <div
                style={{
                  fontFamily: 'var(--font-serif)',
                  fontSize: 18,
                  fontWeight: 800,
                  fontStyle: 'italic',
                  color: 'var(--ink)',
                  lineHeight: 1.1,
                  letterSpacing: '-0.01em',
                }}
              >
                {user.full_name || 'Account'}
              </div>
              <div
                style={{
                  fontSize: 11,
                  color: 'var(--ink-secondary)',
                  marginTop: 4,
                  fontWeight: 400,
                }}
              >
                {user.email}
              </div>
            </div>

            <button
              onClick={() => { setOpen(false); logout() }}
              style={{
                width: '100%',
                padding: '12px 18px',
                background: 'none',
                border: 'none',
                cursor: 'pointer',
                textAlign: 'left',
                fontSize: 10,
                letterSpacing: '0.24em',
                textTransform: 'uppercase',
                color: 'var(--red)',
                fontWeight: 600,
                fontFamily: 'var(--font-body, system-ui, sans-serif)',
                transition: 'background 150ms ease',
              }}
              onMouseEnter={(e) => (e.currentTarget.style.background = 'rgba(192,57,43,0.06)')}
              onMouseLeave={(e) => (e.currentTarget.style.background = 'transparent')}
            >
              Cancel Subscription &nbsp;→
            </button>
          </div>
        </>
      )}
    </div>
  )
}
