'use client'

import { useEffect, useState } from 'react'
import { useRouter } from 'next/navigation'

import { getApiV1Base } from '@/lib/api-v1-base'

interface OutcomeGateModalProps {
  projectId: string
  simulationId: string
  isFullReport: boolean
}

interface GatePayload {
  gate_active: boolean
  prev_project_id?: number
  prev_sim_id?: number
  message?: string
}

export function OutcomeGateModal({ projectId, simulationId, isFullReport }: OutcomeGateModalProps) {
  const router = useRouter()
  const [gateData, setGateData] = useState<GatePayload | null>(null)
  const [launched, setLaunched] = useState<boolean | null>(null)
  const [acr, setAcr] = useState('')
  const [submitted, setSubmitted] = useState(false)

  const token = typeof window !== 'undefined' ? localStorage.getItem('access_token') : null
  const headers: HeadersInit = {
    'Content-Type': 'application/json',
    ...(token ? { Authorization: `Bearer ${token}` } : {}),
  }

  useEffect(() => {
    if (!projectId || isFullReport) return
    const base = getApiV1Base()
    void fetch(`${base}/analytics/check-outcome-gate/${projectId}`, { headers })
      .then((r) => (r.ok ? r.json() : null))
      .then((d: GatePayload | null) => {
        if (d?.gate_active) setGateData(d)
      })
      .catch(() => {})
  }, [projectId, isFullReport])

  const handleSubmit = async () => {
    if (!gateData?.prev_sim_id) return
    const base = getApiV1Base()
    await fetch(`${base}/analytics/founder-outcome`, {
      method: 'POST',
      headers,
      body: JSON.stringify({
        simulation_id: gateData.prev_sim_id,
        launched,
        actual_conversion_rate: acr ? parseFloat(acr) / 100 : null,
      }),
    })
    setSubmitted(true)
    setGateData(null)
    const sp = new URLSearchParams(typeof window !== 'undefined' ? window.location.search : '')
    sp.set('sim', simulationId)
    sp.set('outcome', 'true')
    router.replace(`/project/${projectId}/results?${sp.toString()}`)
  }

  if (!gateData?.gate_active || submitted) return null

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4">
      <div className="w-full max-w-md space-y-5 rounded-2xl border border-slate-700 bg-slate-900 p-6">
        <div>
          <p className="mb-2 font-mono text-xs uppercase tracking-widest text-amber-400">Unlock Full Report</p>
          <h3 className="text-lg font-bold text-white">How did your last simulation perform?</h3>
          <p className="mt-1 text-sm text-slate-400">
            Share what happened with your previous product. Your next simulation becomes more accurate.
          </p>
        </div>

        <div className="space-y-3">
          <p className="text-xs uppercase tracking-widest text-slate-500">Did you launch?</p>
          <div className="flex gap-3">
            {(
              [
                { label: 'Yes, I launched', val: true },
                { label: 'Not yet', val: false },
              ] as const
            ).map((opt) => (
              <button
                key={String(opt.val)}
                type="button"
                onClick={() => setLaunched(opt.val)}
                className={`flex-1 rounded-lg border py-2.5 text-sm transition-all ${
                  launched === opt.val
                    ? 'border-blue-500 bg-blue-500/10 text-white'
                    : 'border-slate-700 text-slate-400'
                }`}
              >
                {opt.label}
              </button>
            ))}
          </div>

          {launched && (
            <input
              value={acr}
              onChange={(e) => setAcr(e.target.value)}
              placeholder="Actual conversion rate % (optional)"
              className="w-full rounded-lg border border-slate-700 bg-slate-800 px-3 py-2 font-mono text-sm text-slate-200 placeholder-slate-600 focus:border-blue-500 focus:outline-none"
            />
          )}
        </div>

        <div className="flex gap-3">
          <button
            type="button"
            onClick={handleSubmit}
            disabled={launched === null}
            className="flex-1 rounded-lg bg-blue-600 py-2.5 text-sm font-bold text-white hover:bg-blue-500 disabled:opacity-40"
          >
            Submit &amp; Unlock
          </button>
          <button
            type="button"
            onClick={() => setGateData(null)}
            className="rounded-lg border border-slate-700 px-4 py-2.5 text-sm text-slate-400 hover:text-slate-200"
          >
            Skip
          </button>
        </div>
      </div>
    </div>
  )
}
