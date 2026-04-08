'use client'

import { useState } from 'react'
import { useLogout } from '@/hooks/useAuth'
import { useAuthStore } from '@/store/auth.store'

export default function UserMenu() {
  const [open, setOpen]  = useState(false)
  const user             = useAuthStore(s => s.user)
  const logout           = useLogout()

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
        style={{
          width: 32, height: 32, borderRadius: '50%',
          background: '#1a1714', border: '.5px solid rgba(26,23,20,.15)',
          display: 'flex', alignItems: 'center', justifyContent: 'center',
          cursor: 'pointer', fontSize: 11, fontFamily: 'system-ui,sans-serif',
          fontWeight: 600, color: '#f2ece0', letterSpacing: '.04em',
        }}
      >
        {initials}
      </button>

      {open && (
        <div style={{
          position: 'absolute', top: 40, right: 0,
          width: 200, background: '#fff',
          border: '.5px solid rgba(26,23,20,.12)',
          borderRadius: 4, padding: '6px 0',
          boxShadow: '0 4px 16px rgba(26,23,20,.08)',
          zIndex: 50,
        }}>
          <div style={{
            padding: '8px 14px 10px',
            borderBottom: '.5px solid rgba(26,23,20,.07)',
          }}>
            <div style={{ fontSize: 12, fontFamily: 'system-ui,sans-serif', color: '#1a1714', fontWeight: 600 }}>
              {user.full_name || 'Account'}
            </div>
            <div style={{ fontSize: 11, fontFamily: 'system-ui,sans-serif', color: 'rgba(26,23,20,.4)' }}>
              {user.email}
            </div>
          </div>
          <button
            onClick={() => { setOpen(false); logout() }}
            style={{
              width: '100%', padding: '8px 14px', background: 'none',
              border: 'none', cursor: 'pointer', textAlign: 'left',
              fontSize: 12, fontFamily: 'system-ui,sans-serif',
              color: '#c0392b',
            }}
          >
            Sign out
          </button>
        </div>
      )}
    </div>
  )
}
