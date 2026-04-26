import axios, { AxiosError, InternalAxiosRequestConfig } from 'axios'
import { auth } from '@/lib/auth'
import { getApiV1Base } from '@/lib/api-v1-base'

/*
  Central API client for all TheCee backend calls.
*/
type RetriableRequestConfig = InternalAxiosRequestConfig & {
  _retry?: boolean
}

const api = axios.create({
  baseURL: getApiV1Base(),
  timeout: 60_000,
  headers: { 'Content-Type': 'application/json' },
})

const refreshClient = axios.create({
  baseURL: getApiV1Base(),
  timeout: 15_000,
  headers: { 'Content-Type': 'application/json' },
})

let refreshPromise: Promise<string | null> | null = null

async function refreshAccessToken(): Promise<string | null> {
  if (typeof window === 'undefined') return null
  const refreshToken = auth.getRefreshToken()
  if (!refreshToken) return null

  if (!refreshPromise) {
    refreshPromise = refreshClient
      .post('/auth/refresh', { refresh_token: refreshToken })
      .then(({ data }) => {
        const accessToken = typeof data?.access_token === 'string' ? data.access_token : null
        const rotatedRefresh = typeof data?.refresh_token === 'string' ? data.refresh_token : null
        if (!accessToken || !rotatedRefresh) {
          throw new Error('Refresh response missing tokens')
        }
        auth.setTokens(accessToken, rotatedRefresh)
        return accessToken
      })
      .catch(() => {
        auth.clearTokens()
        return null
      })
      .finally(() => {
        refreshPromise = null
      })
  }

  return refreshPromise
}

function attachAuthHeader(config: InternalAxiosRequestConfig): InternalAxiosRequestConfig {
  if (typeof window !== 'undefined') {
    const token = auth.getToken()
    if (token && config.headers) {
      config.headers.Authorization = `Bearer ${token}`
    }
  }
  return config
}

api.interceptors.request.use(attachAuthHeader)

api.interceptors.response.use(
  (response) => response,
  async (error: AxiosError) => {
    const status = error.response?.status
    const original = error.config as RetriableRequestConfig | undefined

    if (status === 401 && typeof window !== 'undefined' && original && !original._retry) {
      original._retry = true
      const newAccess = await refreshAccessToken()
      if (newAccess) {
        original.headers = original.headers ?? {}
        original.headers.Authorization = `Bearer ${newAccess}`
        return api.request(original)
      }
      window.location.href = '/login'
    }
    return Promise.reject(error)
  }
)

export default api

export const apiLong = axios.create({
  baseURL: getApiV1Base(),
  timeout: 300_000,   /* 5 minutes for simulation creation + polling */
  headers: { 'Content-Type': 'application/json' },
})

apiLong.interceptors.request.use(attachAuthHeader)

apiLong.interceptors.response.use(
  (response) => response,
  async (error: AxiosError) => {
    const status = error.response?.status
    const original = error.config as RetriableRequestConfig | undefined

    if (status === 401 && typeof window !== 'undefined' && original && !original._retry) {
      original._retry = true
      const newAccess = await refreshAccessToken()
      if (newAccess) {
        original.headers = original.headers ?? {}
        original.headers.Authorization = `Bearer ${newAccess}`
        return apiLong.request(original)
      }
      window.location.href = '/login'
    }
    return Promise.reject(error)
  }
)

export function apiError(err: unknown): string {
  if (axios.isAxiosError(err)) {
    const detail = err.response?.data?.detail as unknown
    if (typeof detail === 'string') return detail
    if (Array.isArray(detail)) {
      return detail.map((d: { msg?: string }) => d.msg).filter(Boolean).join(', ')
    }
  }
  if (err instanceof Error) return err.message
  return 'An unexpected error occurred'
}
