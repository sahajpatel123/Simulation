import { useCallback, useEffect, useState } from 'react'
import { auth } from '@/lib/auth'
import api from '@/lib/api'
import { notify } from '@/lib/toast'

interface SessionExpiryOptions {
  bufferSeconds?: number
  warnSeconds?: number
  autoRefresh?: boolean
  checkIntervalMs?: number
}

interface SessionExpiryState {
  secondsRemaining: number | null
  isNearExpiry: boolean
  isExpired: boolean
  isRefreshing: boolean
  refreshSession: () => Promise<boolean>
}

/**
 * Hook to track access token expiration countdown, offer silent auto-refresh,
 * and surface warning notifications before session termination.
 */
export function useSessionExpiry(options: SessionExpiryOptions = {}): SessionExpiryState {
  const {
    bufferSeconds = 300,
    warnSeconds = 120,
    autoRefresh = true,
    checkIntervalMs = 10_000,
  } = options

  const [secondsRemaining, setSecondsRemaining] = useState<number | null>(() =>
    auth.getAccessTokenSecondsRemaining()
  )
  const [isRefreshing, setIsRefreshing] = useState<boolean>(false)
  const [hasWarned, setHasWarned] = useState<boolean>(false)

  const refreshSession = useCallback(async (): Promise<boolean> => {
    const refreshToken = auth.getRefreshToken()
    if (!refreshToken) return false

    setIsRefreshing(true)
    try {
      const { data } = await api.post('/auth/refresh', { refresh_token: refreshToken })
      if (data?.access_token && data?.refresh_token) {
        auth.setTokens(data.access_token, data.refresh_token)
        const newRemaining = auth.getAccessTokenSecondsRemaining()
        setSecondsRemaining(newRemaining)
        setHasWarned(false)
        return true
      }
      return false
    } catch {
      return false
    } finally {
      setIsRefreshing(false)
    }
  }, [])

  useEffect(() => {
    if (typeof window === 'undefined') return

    const updateState = async () => {
      const remaining = auth.getAccessTokenSecondsRemaining()
      setSecondsRemaining(remaining)

      if (remaining === null) return

      /* Warn user when session is critically low */
      if (remaining > 0 && remaining <= warnSeconds && !hasWarned) {
        notify.info('Your session is expiring soon. We are extending your session.')
        setHasWarned(true)
      }

      /* Auto refresh when within buffer */
      if (autoRefresh && remaining > 0 && remaining <= bufferSeconds && !isRefreshing) {
        await refreshSession()
      }
    }

    updateState()
    const timer = setInterval(updateState, checkIntervalMs)
    return () => clearInterval(timer)
  }, [autoRefresh, bufferSeconds, checkIntervalMs, hasWarned, isRefreshing, refreshSession, warnSeconds])

  const isNearExpiry = secondsRemaining !== null && secondsRemaining > 0 && secondsRemaining <= bufferSeconds
  const isExpired = secondsRemaining === 0

  return {
    secondsRemaining,
    isNearExpiry,
    isExpired,
    isRefreshing,
    refreshSession,
  }
}
