'use client'

import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { getPersonaName, getPersonaTagline } from '@/lib/cluster-personas'
import { getApiV1Base } from '@/lib/api-v1-base'

const apiV1 = () => getApiV1Base()

interface Delta {
  conversion_delta: number
  previous_conversion: number
  older_conversion: number
  direction: 'UP' | 'DOWN' | 'FLAT'
  most_improved: Array<{ cluster_id: string; delta: number }>
  most_degraded: Array<{ cluster_id: string; delta: number }>
  assumptions_changed: number
  simulation_count: number
}

interface ReSimulateButtonProps {
  projectId: string
  onComplete?: (newSimId: number) => void
}

function DeltaBadge({ delta }: { delta: number }) {
  if (delta === 0) return null
  const up = delta > 0
  const pct = `${up ? '+' : ''}${(delta * 100).toFixed(1)}%`
  return (
    <span
      className={`inline-flex items-center gap-1 px-2 py-0.5 rounded text-xs font-mono font-bold ${
        up ? 'bg-green-500/15 text-green-400' : 'bg-red-500/15 text-red-400'
      }`}
    >
      {up ? '↑' : '↓'} {pct}
    </span>
  )
}

export function ReSimulateButton({ projectId, onComplete }: ReSimulateButtonProps) {
  const [showDelta, setShowDelta] = useState(false)
  const [lastDelta, setLastDelta] = useState<Delta | null>(null)
  const queryClient = useQueryClient()

  const token = typeof window !== 'undefined' ? localStorage.getItem('access_token') : null
  const headers: HeadersInit = {
    'Content-Type': 'application/json',
    ...(token ? { Authorization: `Bearer ${token}` } : {}),
  }

  const { data: historyData } = useQuery({
    queryKey: ['sim-history', projectId],
    queryFn: async () => {
      const r = await fetch(`${apiV1()}/projects/${projectId}/simulation-history`, { headers })
      if (!r.ok) throw new Error(await r.text())
      return r.json() as Promise<{
        history: Array<{
          simulation_id: number
          conversion_rate: number
          delta_from_prev: number | null
          direction: string | null
        }>
        total_runs: number
      }>
    },
    enabled: !!projectId,
  })

  const history = historyData?.history ?? []
  const totalRuns = historyData?.total_runs ?? 0
  const latestDelta =
    history.length >= 2 ? history[history.length - 1]?.delta_from_prev : null

  const reSimMutation = useMutation({
    mutationFn: async () => {
      const r = await fetch(`${apiV1()}/projects/${projectId}/re-simulate`, {
        method: 'POST',
        headers,
        body: JSON.stringify({}),
      })
      if (!r.ok) throw new Error(await r.text())
      return r.json() as Promise<{
        new_simulation_id: number
        delta?: Delta | null
      }>
    },
    onSuccess: (data) => {
      void queryClient.invalidateQueries({ queryKey: ['sim-history', projectId] })
      if (data.delta) {
        setLastDelta(data.delta)
        setShowDelta(true)
      }
      if (data.new_simulation_id) {
        onComplete?.(data.new_simulation_id)
      }
    },
  })

  const delta: Delta | null =
    lastDelta ??
    (history.length >= 2
      ? {
          conversion_delta: history[history.length - 1]?.delta_from_prev ?? 0,
          previous_conversion: history[history.length - 1]?.conversion_rate ?? 0,
          older_conversion: history[history.length - 2]?.conversion_rate ?? 0,
          direction: (history[history.length - 1]?.direction ?? 'FLAT') as Delta['direction'],
          most_improved: [],
          most_degraded: [],
          assumptions_changed: 0,
          simulation_count: totalRuns,
        }
      : null)

  return (
    <div className="space-y-4">
      <div className="flex items-center gap-3">
        <button
          type="button"
          onClick={() => reSimMutation.mutate()}
          disabled={reSimMutation.isPending}
          className="flex items-center gap-2 px-5 py-2.5 bg-blue-600 hover:bg-blue-500
                     disabled:opacity-40 disabled:cursor-not-allowed rounded-lg
                     text-sm font-bold font-mono tracking-widest uppercase transition-all"
        >
          {reSimMutation.isPending ? (
            <>
              <span
                className="w-3 h-3 border-2 border-white border-t-transparent
                               rounded-full animate-spin"
              />
              Queuing...
            </>
          ) : (
            <>↺ Re-Simulate</>
          )}
        </button>

        <span className="text-xs font-mono text-slate-600">
          Run {totalRuns + 1}
          {totalRuns > 0 && <span className="ml-1 text-slate-700">of {totalRuns + 1}</span>}
        </span>

        {latestDelta !== null && latestDelta !== undefined && <DeltaBadge delta={latestDelta} />}
      </div>

      {showDelta && delta && (
        <div className="bg-slate-900 border border-slate-800 rounded-xl overflow-hidden transition-opacity">
          <div className="p-5 space-y-4">
              <div className="flex items-center justify-between">
                <div>
                  <p className="text-xs font-mono tracking-widest uppercase text-slate-600 mb-1">
                    Conversion Delta
                  </p>
                  <div className="flex items-center gap-3">
                    <span className="text-2xl font-bold font-mono text-slate-500">
                      {(delta.older_conversion * 100).toFixed(1)}%
                    </span>
                    <span className="text-slate-700">→</span>
                    <span className="text-2xl font-bold font-mono text-white">
                      {(delta.previous_conversion * 100).toFixed(1)}%
                    </span>
                    <DeltaBadge delta={delta.conversion_delta} />
                  </div>
                </div>
                <button
                  type="button"
                  onClick={() => setShowDelta(false)}
                  className="text-slate-700 hover:text-slate-400 text-xs font-mono"
                >
                  dismiss
                </button>
              </div>

              {(delta.most_improved.length > 0 || delta.most_degraded.length > 0) && (
                <div className="space-y-2">
                  <p className="text-xs font-mono tracking-widest uppercase text-slate-600">
                    Cluster Changes
                  </p>

                  {delta.most_improved.slice(0, 2).map((item) => (
                    <div
                      key={item.cluster_id}
                      className="flex items-center justify-between bg-green-500/5
                                 border border-green-500/20 rounded-lg px-4 py-2.5"
                    >
                      <div>
                        <span className="text-sm text-white font-mono">
                          {getPersonaName(item.cluster_id)}
                        </span>
                        <span className="text-xs text-slate-500 ml-2">
                          {getPersonaTagline(item.cluster_id)}
                        </span>
                      </div>
                      <DeltaBadge delta={item.delta} />
                    </div>
                  ))}

                  {delta.most_degraded.slice(0, 2).map((item) => (
                    <div
                      key={item.cluster_id}
                      className="flex items-center justify-between bg-red-500/5
                                 border border-red-500/20 rounded-lg px-4 py-2.5"
                    >
                      <div>
                        <span className="text-sm text-white font-mono">
                          {getPersonaName(item.cluster_id)}
                        </span>
                        <span className="text-xs text-slate-500 ml-2">
                          {getPersonaTagline(item.cluster_id)}
                        </span>
                      </div>
                      <DeltaBadge delta={item.delta} />
                    </div>
                  ))}
                </div>
              )}

              <p className="text-xs font-mono text-slate-500 border-t border-slate-800 pt-3">
                {delta.direction === 'UP' ? (
                  <>
                    {delta.most_improved[0] && (
                      <>
                        You improved conversion for{' '}
                        <span className="text-green-400">
                          {getPersonaName(delta.most_improved[0].cluster_id)}
                        </span>{' '}
                        (+{(delta.most_improved[0].delta * 100).toFixed(1)}%)
                      </>
                    )}
                    {delta.most_degraded[0] && (
                      <>
                        {' '}
                        but lost{' '}
                        <span className="text-red-400">
                          {getPersonaName(delta.most_degraded[0].cluster_id)}
                        </span>{' '}
                        ({(delta.most_degraded[0].delta * 100).toFixed(1)}%).
                      </>
                    )}
                  </>
                ) : delta.direction === 'DOWN' ? (
                  <>
                    Overall conversion dropped {(Math.abs(delta.conversion_delta) * 100).toFixed(1)}%.
                    {delta.most_degraded[0] && (
                      <>
                        {' '}
                        {getPersonaName(delta.most_degraded[0].cluster_id)} is the primary loss.
                      </>
                    )}
                  </>
                ) : (
                  'Conversion unchanged from previous run.'
                )}
              </p>
          </div>
        </div>
      )}

      {history.length >= 2 && (
        <div className="space-y-2">
          <p className="text-xs font-mono tracking-widest uppercase text-slate-700">
            Iteration History
          </p>
          <div className="flex items-end gap-2 h-12">
            {history.map((run, i) => {
              const maxCr = Math.max(...history.map((r) => r.conversion_rate))
              const barH = maxCr > 0 ? Math.max(4, (run.conversion_rate / maxCr) * 48) : 4
              const isLatest = i === history.length - 1
              return (
                <div
                  key={run.simulation_id}
                  className="flex flex-col items-center gap-1 group cursor-pointer"
                >
                  <div
                    className={`w-4 rounded-t transition-all ${
                      isLatest
                        ? 'bg-blue-500'
                        : run.direction === 'UP'
                          ? 'bg-green-500/60'
                          : run.direction === 'DOWN'
                            ? 'bg-red-500/60'
                            : 'bg-slate-700'
                    }`}
                    style={{ height: `${barH}px` }}
                    title={`Run ${i + 1}: ${(run.conversion_rate * 100).toFixed(1)}%`}
                  />
                  <span className="text-xs font-mono text-slate-700 group-hover:text-slate-500">
                    {i + 1}
                  </span>
                </div>
              )
            })}
          </div>
        </div>
      )}
    </div>
  )
}
