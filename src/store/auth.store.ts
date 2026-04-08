import { create } from 'zustand'
import { auth } from '@/lib/auth'

export interface AuthUser {
  id:         number
  email:      string
  full_name:  string | null
  created_at: string
}

interface AuthState {
  user:          AuthUser | null
  isHydrated:    boolean   /* true once localStorage has been read */
  setUser:       (user: AuthUser | null) => void
  hydrate:       () => void
  logout:        () => void
}

export const useAuthStore = create<AuthState>((set) => ({
  user:       null,
  isHydrated: false,

  setUser: (user) => {
    if (user) auth.setUser(user as unknown as Record<string, unknown>)
    set({ user })
  },

  /*
    hydrate() reads the persisted user from localStorage into
    the Zustand store. Call this once in the root layout on
    mount — avoids a flash of unauthenticated state on refresh.
  */
  hydrate: () => {
    const raw = auth.getUser()
    set({
      user:       raw ? (raw as unknown as AuthUser) : null,
      isHydrated: true,
    })
  },

  logout: () => {
    auth.clearTokens()
    set({ user: null, isHydrated: true })
    if (typeof window !== 'undefined') {
      window.location.href = '/login'
    }
  },
}))
