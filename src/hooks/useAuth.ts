import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useRouter } from 'next/navigation'
import api, { apiError } from '@/lib/api'
import { auth } from '@/lib/auth'
import { useAuthStore, type AuthUser } from '@/store/auth.store'

export { apiError }

type AuthTokensResponse = {
  access_token: string
  refresh_token?: string
  user?: AuthUser
}

/* ── Login ── */
export const useLogin = () => {
  const setUser   = useAuthStore(s => s.setUser)
  const router    = useRouter()
  const qc        = useQueryClient()

  return useMutation({
    mutationFn: async ({
      email,
      password,
    }: {
      email: string
      password: string
    }) => {
      const { data } = await api.post('/auth/login', { email, password })
      return data as AuthTokensResponse
    },
    onSuccess: async (tokens) => {
      auth.setTokens(tokens.access_token, tokens.refresh_token)
      if (tokens.user) {
        setUser(tokens.user)
      } else {
        /* Fetch the user profile immediately after login */
        try {
          const { data: user } = await api.get<AuthUser>('/auth/me')
          setUser(user)
        } catch {
          /* Non-fatal — we have a token, just no profile cache */
        }
      }
      qc.clear()   /* clear any stale unauthenticated query cache */
      router.push('/')
    },
  })
}

/* ── Register ── */
export const useRegister = () => {
  const router = useRouter()
  const qc     = useQueryClient()

  return useMutation({
    mutationFn: async ({
      email,
      password,
      full_name,
    }: {
      email:     string
      password:  string
      full_name: string
    }) => {
      const { data } = await api.post('/auth/register', { email, password, full_name })
      return data as AuthTokensResponse
    },
    onSuccess: async (tokens) => {
      auth.setTokens(tokens.access_token, tokens.refresh_token)
      if (tokens.user) {
        useAuthStore.getState().setUser(tokens.user)
      } else {
        /* Fetch the user profile immediately after login */
        try {
          const { data: user } = await api.get<AuthUser>('/auth/me')
          useAuthStore.getState().setUser(user)
        } catch {
          /* Non-fatal — we have a token, just no profile cache */
        }
      }
      qc.clear()
      router.push('/')
    },
  })
}

/* ── Current user (server-validated) ── */
export const useCurrentUser = () => {
  const setUser = useAuthStore(s => s.setUser)
  return useQuery<AuthUser>({
    queryKey: ['me'],
    queryFn:  async () => {
      const { data } = await api.get<AuthUser>('/auth/me')
      /* Keep the auth store in sync so settings fields rehydrate on reload. */
      setUser(data)
      return data
    },
    enabled:  auth.isAuthenticated(),
    staleTime: 1000 * 60 * 10,   /* re-fetch every 10 minutes */
    retry: (count, err: unknown) => {
      const status = (err as { response?: { status: number } })?.response?.status
      return status !== 401 && count < 1
    },
  })
}

/* ── Logout ── */
export const useLogout = () => {
  const logout = useAuthStore(s => s.logout)
  const qc     = useQueryClient()

  return async () => {
    const refreshToken = auth.getRefreshToken()
    const hasSession = auth.getToken() && refreshToken
    if (hasSession) {
      try {
        await api.post('/auth/logout')
      } catch {
        /* Local logout still proceeds if the network is down or token is already invalid. */
      }
    }
    qc.clear()
    logout()
  }
}
