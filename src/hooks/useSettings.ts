import { useMutation, useQueryClient } from '@tanstack/react-query'
import api from '@/lib/api'
import { useAuthStore, type AuthUser } from '@/store/auth.store'

/* ── Profile / settings PATCH ───────────────────────────────── */
export type ProfileUpdatePayload = Partial<{
  full_name:            string | null
  email:                string
  handle:               string | null

  reduced_motion:       boolean
  email_notices:        boolean
  weekly_brief:         boolean
  default_units:        'inr' | 'usd' | 'eur'

  default_reader_count: number
  default_scenario:     'base' | 'recession' | 'viral' | 'competitor'
  default_aov:          number
  keep_past_results:    boolean
}>

export const useUpdateProfile = () => {
  const setUser = useAuthStore((s) => s.setUser)
  const qc      = useQueryClient()

  return useMutation({
    mutationFn: async (payload: ProfileUpdatePayload) => {
      const { data } = await api.patch<AuthUser>('/auth/me', payload)
      return data
    },
    onSuccess: (user) => {
      setUser(user)
      qc.setQueryData(['me'], user)
    },
  })
}

/* ── Change password ────────────────────────────────────────── */
export const useChangePassword = () =>
  useMutation({
    mutationFn: async (payload: { current_password: string; new_password: string }) => {
      const { data } = await api.post<{ message: string }>('/auth/change-password', payload)
      return data
    },
  })

/* ── Clear archive (delete every dossier) ───────────────────── */
export const useClearArchive = () => {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async () => {
      const { data } = await api.post<{ message: string }>('/users/me/clear-archive')
      return data
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['projects'] })
    },
  })
}

/* ── Delete account ─────────────────────────────────────────── */
export const useDeleteAccount = () => {
  const logout = useAuthStore((s) => s.logout)
  const qc     = useQueryClient()
  return useMutation({
    mutationFn: async (payload: { password: string }) => {
      const { data } = await api.delete<{ message: string }>('/auth/me', { data: payload })
      return data
    },
    onSuccess: () => {
      qc.clear()
      logout()
    },
  })
}

/* ── Export archive (download JSON) ─────────────────────────── */
export const useExportArchive = () =>
  useMutation({
    mutationFn: async () => {
      const { data } = await api.get<Record<string, unknown>>('/users/me/export')
      const blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' })
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      const stamp = new Date().toISOString().slice(0, 10)
      a.href = url
      a.download = `thecee-archive-${stamp}.json`
      document.body.appendChild(a)
      a.click()
      document.body.removeChild(a)
      URL.revokeObjectURL(url)
      return data
    },
  })
