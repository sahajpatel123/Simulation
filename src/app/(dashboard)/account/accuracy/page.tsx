'use client'

import { useQuery } from '@tanstack/react-query'
import { useRouter } from 'next/navigation'

import { getApiV1Base } from '@/lib/api-v1-base'

type AccuracyResponse = {
  has_data: boolean
  message?: string
  mean_gap: number | null
  trend: string | null
  history?: Array<{
    simulation_id: number
    predicted: number
    actual: number
    gap: number
    created_at: string | null
  }>
  biases?: Array<{
    architect: string
    direction: string
    reliability: number
  }>
  blindspots?: Array<{
    type: string
    value: string
    occurrence_count: number
  }>
}

export default function AccuracyPage() {
  const router = useRouter()
  const token = typeof window !== 'undefined' ? localStorage.getItem('access_token') : null
  const headers: HeadersInit = {
    ...(token ? { Authorization: `Bearer ${token}` } : {}),
  }

  const { data, isLoading } = useQuery<AccuracyResponse>({
    queryKey: ['my-accuracy'],
    queryFn: async () => {
      const r = await fetch(`${getApiV1Base()}/calibration/my-accuracy`, { headers })
      if (!r.ok) throw new Error('Failed to load accuracy')
      return r.json() as Promise<AccuracyResponse>
    },
  })

  const trendColor = (t: string | null) =>
    t === 'IMPROVING' ? 'var(--workshop, #2dd4bf)' : t === 'WIDENING' ? 'var(--red, #f87171)' : 'var(--ink-secondary)'

  if (isLoading) {
    return (
      <div className="min-h-[50vh] flex items-center justify-center" style={{ color: 'var(--ink-secondary)' }}>
        <div
          className="w-6 h-6 border-2 border-t-transparent rounded-full animate-spin"
          style={{ borderColor: 'var(--border-strong)', borderTopColor: 'transparent' }}
        />
      </div>
    )
  }

  return (
    <div
      className="max-w-3xl mx-auto p-8 font-mono"
      style={{ color: 'var(--ink)', background: 'var(--paper)' }}
    >
      <p className="text-xs tracking-widest uppercase mb-1" style={{ color: 'var(--accent)' }}>
        Account / Accuracy
      </p>
      <h1 className="text-xl font-bold mb-6" style={{ color: 'var(--ink)' }}>
        Your Simulation Accuracy
      </h1>

      {!data?.has_data ? (
        <div
          className="rounded-2xl p-8 text-center border"
          style={{ background: 'var(--card)', borderColor: 'var(--border-color)' }}
        >
          <p className="text-sm mb-2" style={{ color: 'var(--ink-secondary)' }}>
            {data?.message}
          </p>
          <button
            type="button"
            onClick={() => router.push('/projects')}
            className="mt-4 px-5 py-2.5 rounded-lg text-sm font-bold tracking-widest uppercase"
            style={{ background: 'var(--accent)', color: 'var(--paper)' }}
          >
            Return with real data →
          </button>
        </div>
      ) : (
        <div className="space-y-6">
          <div className="grid grid-cols-2 gap-4">
            <div
              className="rounded-xl p-5 border"
              style={{ background: 'var(--card)', borderColor: 'var(--border-color)' }}
            >
              <p className="text-xs tracking-widest uppercase mb-2" style={{ color: 'var(--ink-secondary)' }}>
                Mean Prediction Gap
              </p>
              <p className="text-3xl font-bold" style={{ color: 'var(--accent)' }}>
                {data?.mean_gap !== null && data?.mean_gap !== undefined
                  ? `${(data.mean_gap * 100).toFixed(1)}%`
                  : '—'}
              </p>
              <p className="text-xs mt-1" style={{ color: 'var(--ink-tertiary, var(--ink-secondary))' }}>
                lower is more accurate
              </p>
            </div>
            <div
              className="rounded-xl p-5 border"
              style={{ background: 'var(--card)', borderColor: 'var(--border-color)' }}
            >
              <p className="text-xs tracking-widest uppercase mb-2" style={{ color: 'var(--ink-secondary)' }}>
                Accuracy Trend
              </p>
              <p className="text-3xl font-bold" style={{ color: trendColor(data?.trend ?? null) }}>
                {data?.trend ?? '—'}
              </p>
              <p className="text-xs mt-1" style={{ color: 'var(--ink-tertiary, var(--ink-secondary))' }}>
                last 3 outcomes
              </p>
            </div>
          </div>

          {data?.history && data.history.length > 0 ? (
            <div
              className="rounded-xl p-5 border"
              style={{ background: 'var(--card)', borderColor: 'var(--border-color)' }}
            >
              <p className="text-xs tracking-widest uppercase mb-4" style={{ color: 'var(--ink-secondary)' }}>
                Prediction vs Actual
              </p>
              <div className="space-y-3">
                {data.history.map((h, i) => (
                  <div key={`${h.simulation_id}-${i}`} className="space-y-1">
                    <div className="flex items-center justify-between text-xs" style={{ color: 'var(--ink-secondary)' }}>
                      <span>Run {i + 1}</span>
                      <span>Gap: {(h.gap * 100).toFixed(1)}%</span>
                    </div>
                    <div className="flex gap-1 h-2">
                      <div
                        className="rounded-full"
                        style={{ width: `${Math.min(100, h.predicted * 100 * 2)}%`, background: 'var(--accent)' }}
                        title={`Predicted: ${(h.predicted * 100).toFixed(1)}%`}
                      />
                      <div
                        className="rounded-full"
                        style={{ width: `${Math.min(100, h.actual * 100 * 2)}%`, background: 'var(--workshop, #14b8a6)' }}
                        title={`Actual: ${(h.actual * 100).toFixed(1)}%`}
                      />
                    </div>
                    <div className="flex gap-4 text-xs">
                      <span style={{ color: 'var(--accent)' }}>■ Predicted {(h.predicted * 100).toFixed(1)}%</span>
                      <span style={{ color: 'var(--workshop, #14b8a6)' }}>■ Actual {(h.actual * 100).toFixed(1)}%</span>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          ) : null}

          {data?.biases && data.biases.length > 0 ? (
            <div
              className="rounded-xl p-5 border"
              style={{ background: 'var(--card)', borderColor: 'var(--border-color)' }}
            >
              <p className="text-xs tracking-widest uppercase mb-3" style={{ color: 'var(--ink-secondary)' }}>
                Your Consistent Biases
              </p>
              <div className="space-y-2">
                {data.biases.map((b) => (
                  <div key={b.architect} className="flex items-center justify-between text-sm">
                    <span style={{ color: 'var(--ink)' }}>{b.architect}</span>
                    <div className="flex items-center gap-3">
                      <span className="text-xs" style={{ color: 'var(--workshop)' }}>
                        {b.direction}
                      </span>
                      <span className="text-xs" style={{ color: 'var(--ink-secondary)' }}>
                        {(b.reliability * 100).toFixed(0)}% reliable
                      </span>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          ) : null}

          {data?.blindspots && data.blindspots.length > 0 ? (
            <div
              className="rounded-xl p-5 border"
              style={{ background: 'var(--card)', borderColor: 'var(--border-color)' }}
            >
              <p className="text-xs tracking-widest uppercase mb-3" style={{ color: 'var(--ink-secondary)' }}>
                Recurring Blindspots
              </p>
              {data.blindspots.map((b) => (
                <div
                  key={`${b.type}-${b.value}`}
                  className="flex items-center justify-between py-2 border-b last:border-0"
                  style={{ borderColor: 'var(--border-color)' }}
                >
                  <div>
                    <p className="text-sm" style={{ color: 'var(--ink)' }}>
                      {b.type?.replace(/_/g, ' ')}
                    </p>
                    <p className="text-xs" style={{ color: 'var(--ink-secondary)' }}>
                      {b.value}
                    </p>
                  </div>
                  <span className="text-xs" style={{ color: 'var(--ink-secondary)' }}>
                    seen {b.occurrence_count}×
                  </span>
                </div>
              ))}
            </div>
          ) : null}

          <div
            className="rounded-xl p-5 border"
            style={{
              background: 'color-mix(in srgb, var(--accent) 10%, var(--card))',
              borderColor: 'var(--border-strong)',
            }}
          >
            <p className="text-sm mb-3" style={{ color: 'var(--ink)' }}>
              {data?.message}
            </p>
            <button
              type="button"
              onClick={() => router.push('/projects')}
              className="px-5 py-2.5 rounded-lg text-sm font-bold tracking-widest uppercase transition-all"
              style={{ background: 'var(--accent)', color: 'var(--paper)' }}
            >
              Return with real data →
            </button>
          </div>
        </div>
      )}
    </div>
  )
}
